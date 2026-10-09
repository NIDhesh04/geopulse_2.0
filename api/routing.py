import asyncpg

class RoutingService:
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.pool = None

    async def connect(self):
        if not self.pool:
            self.pool = await asyncpg.create_pool(self.db_url)

    async def close(self):
        if self.pool:
            await self.pool.close()

    async def route(self, start_lat: float, start_lon: float, end_lat: float, end_lon: float):
        start_edge = await self.snap_to_edge(start_lat, start_lon)
        end_edge = await self.snap_to_edge(end_lat, end_lon)
        
        if not start_edge or not end_edge:
            return None

        # pgr_dijkstra expects node IDs, snapping here returns source and target from ways table.
        # This is a simplified wrapper query assuming we have edge source/target
        query = """
        SELECT seq, path_seq, node, edge, cost, agg_cost 
        FROM pgr_dijkstra(
            'SELECT id, source_node_id as source, target_node_id as target, cost FROM ways',
            $1, $2, directed := false
        )
        """
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query, start_edge['source_node_id'], end_edge['target_node_id'])
            return [dict(r) for r in records]

    async def snap_to_edge(self, lat: float, lon: float):
        # ST_DWithin and <-> GiST index for nearest neighbor
        query = """
        SELECT id, source_node_id, target_node_id 
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
        WHERE w.id = m.id
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, ids, mults)

    async def get_multipliers(self):
        query = "SELECT id, cost / NULLIF(length_m, 0) as multiplier FROM ways"
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query)
            return {r['id']: r['multiplier'] for r in records if r['multiplier'] is not None}

    async def reset_multipliers(self):
        query = "UPDATE ways SET cost = length_m"
        async with self.pool.acquire() as conn:
            await conn.execute(query)
