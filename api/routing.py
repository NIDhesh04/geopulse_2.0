import asyncio
import asyncpg

class RoutingService:
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.pool = None

    async def connect(self):
        if not self.pool:
            self.pool = await asyncpg.create_pool(self.db_url, min_size=10, max_size=50)

    async def close(self):
        if self.pool:
            await self.pool.close()

    async def route(self, start_lat: float, start_lon: float, end_lat: float, end_lon: float, static: bool = False):
        start_edge, end_edge = await asyncio.gather(
            self.snap_to_edge(start_lat, start_lon),
            self.snap_to_edge(end_lat, end_lon)
        )
        
        if not start_edge or not end_edge:
            return None

        # Use directed:=true and include reverse_cost for one-way streets
        # If static=True, we use length_m (base cost) instead of the dynamic 'cost' column.
        cost_col = "length_m" if static else "cost"
        
        query = f"""
        SELECT seq, path_seq, node, edge, cost, agg_cost 
        FROM pgr_dijkstra(
            'SELECT gid as id, source, target, {cost_col} as cost, CASE WHEN reverse_cost < 0 THEN -1 ELSE {cost_col} END as reverse_cost FROM ways',
            $1::bigint, $2::bigint, directed := true
        )
        """
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query, start_edge['source_node_id'], end_edge['target_node_id'])
            return [dict(r) for r in records]

    async def snap_to_edge(self, lat: float, lon: float):
        # ST_DWithin and <-> GiST index for nearest neighbor
        query = """
        SELECT gid as id, source as source_node_id, target as target_node_id 
        FROM ways 
        WHERE ST_DWithin(the_geom, ST_SetSRID(ST_MakePoint($1, $2), 4326), 0.01)
        ORDER BY the_geom <-> ST_SetSRID(ST_MakePoint($1, $2), 4326)
        LIMIT 1
        """
        async with self.pool.acquire() as conn:
            record = await conn.fetchrow(query, lon, lat)
            return dict(record) if record else None

    async def apply_multipliers(self, multipliers_dict: dict):
        if not multipliers_dict:
            return

        # Prepare unnest arrays
        ids = list(multipliers_dict.keys())
        mults = list(multipliers_dict.values())
        
        # Original cost should ideally be preserved; assuming base_cost * multiplier.
        # For simplicity, if cost is dynamic, we update the current cost column.
        query = """
        UPDATE ways AS w
        SET cost = w.length_m * m.multiplier
        FROM unnest($1::bigint[], $2::float[]) AS m(id, multiplier)
        WHERE w.gid = m.id
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, ids, mults)

    async def get_multipliers(self):
        query = "SELECT gid as id, cost / NULLIF(length_m, 0) as multiplier FROM ways"
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query)
            return {r['id']: r['multiplier'] for r in records if r['multiplier'] is not None}

    async def reset_multipliers(self):
        query = "UPDATE ways SET cost = length_m"
        async with self.pool.acquire() as conn:
            await conn.execute(query)
