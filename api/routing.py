import asyncio
import logging
import asyncpg
from asyncpg.exceptions import PostgresConnectionError, CannotConnectNowError, InterfaceError

logger = logging.getLogger("routing")

class DatabaseUnavailableError(Exception):
    """Raised when the routing database is unavailable or unreachable."""
    pass

class RoutingService:
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.pool = None
        self.db_active = False

    async def connect(self):
        if not self.pool:
            try:
                self.pool = await asyncio.wait_for(
                    asyncpg.create_pool(self.db_url, min_size=10, max_size=50, command_timeout=5.0),
                    timeout=5.0
                )
                self.db_active = True
            except (PostgresConnectionError, CannotConnectNowError, asyncio.TimeoutError, TimeoutError, OSError, InterfaceError) as e:
                self.pool = None
                logger.error(f"Failed to connect to database: {e}")
                raise DatabaseUnavailableError(f"Database unavailable: {e}") from e

    async def close(self):
        if self.pool:
            try:
                await self.pool.close()
            except Exception as e:
                logger.warning(f"Error closing DB pool: {e}")
            finally:
                self.pool = None

    async def check_health(self) -> bool:
        if not self.pool:
            try:
                await asyncio.wait_for(self.connect(), timeout=1.0)
            except Exception:
                return False
        if not self.pool:
            return False
        try:
            async with self.pool.acquire() as conn:
                await asyncio.wait_for(conn.fetchval("SELECT 1"), timeout=1.0)
            return True
        except (PostgresConnectionError, CannotConnectNowError, asyncio.TimeoutError, TimeoutError, OSError, InterfaceError):
            self.pool = None
            return False

    async def route(
        self, 
        start_lat: float, 
        start_lon: float, 
        end_lat: float, 
        end_lon: float, 
        static: bool = False,
        algorithm: str = "dijkstra"
    ):
        if not self.pool:
            try:
                await asyncio.wait_for(self.connect(), timeout=2.0)
            except Exception as e:
                raise DatabaseUnavailableError(f"Database unavailable: {e}") from e

        try:
            start_edge, end_edge = await asyncio.gather(
                self.snap_to_edge(start_lat, start_lon),
                self.snap_to_edge(end_lat, end_lon)
            )
            
            if not start_edge or not end_edge:
                return None

            # Use directed:=true and include reverse_cost for one-way streets
            # If static=True, we use length_m (base cost) instead of the dynamic 'cost' column.
            cost_col = "length_m" if static else "cost"
            
            if algorithm.lower() == "astar":
                # pgr_aStar with Euclidean coordinates x1, y1, x2, y2
                query = f"""
                SELECT seq, path_seq, node, edge, cost, agg_cost 
                FROM pgr_aStar(
                    'SELECT gid as id, source, target, {cost_col} as cost, CASE WHEN reverse_cost < 0 THEN -1 ELSE {cost_col} END as reverse_cost, x1, y1, x2, y2 FROM ways',
                    $1::bigint, $2::bigint, directed := true, heuristic := 5
                )
                """
            else:
                query = f"""
                SELECT seq, path_seq, node, edge, cost, agg_cost 
                FROM pgr_dijkstra(
                    'SELECT gid as id, source, target, {cost_col} as cost, CASE WHEN reverse_cost < 0 THEN -1 ELSE {cost_col} END as reverse_cost FROM ways',
                    $1::bigint, $2::bigint, directed := true
                )
                """

            async with self.pool.acquire() as conn:
                records = await asyncio.wait_for(
                    conn.fetch(query, start_edge['source_node_id'], end_edge['target_node_id']),
                    timeout=5.0
                )
                return [dict(r) for r in records]
        except DatabaseUnavailableError:
            raise
        except (PostgresConnectionError, CannotConnectNowError, asyncio.TimeoutError, TimeoutError, OSError, InterfaceError) as e:
            self.pool = None
            logger.error(f"Database error during routing: {e}")
            raise DatabaseUnavailableError(f"Database unavailable during routing: {e}") from e

    async def snap_to_edge(self, lat: float, lon: float):
        if not self.pool:
            try:
                await asyncio.wait_for(self.connect(), timeout=2.0)
            except Exception as e:
                raise DatabaseUnavailableError(f"Database unavailable: {e}") from e

        # ST_DWithin and <-> GiST index for nearest neighbor
        query = """
        SELECT gid as id, source as source_node_id, target as target_node_id 
        FROM ways 
        WHERE ST_DWithin(the_geom, ST_SetSRID(ST_MakePoint($1, $2), 4326), 0.01)
        ORDER BY the_geom <-> ST_SetSRID(ST_MakePoint($1, $2), 4326)
        LIMIT 1
        """
        try:
            async with self.pool.acquire() as conn:
                record = await asyncio.wait_for(conn.fetchrow(query, lon, lat), timeout=3.0)
                return dict(record) if record else None
        except DatabaseUnavailableError:
            raise
        except (PostgresConnectionError, CannotConnectNowError, asyncio.TimeoutError, TimeoutError, OSError, InterfaceError) as e:
            self.pool = None
            logger.error(f"Database error during snap_to_edge: {e}")
            raise DatabaseUnavailableError(f"Database unavailable during snap_to_edge: {e}") from e

    async def apply_multipliers(self, multipliers_dict: dict):
        if not multipliers_dict:
            return
        if not self.pool:
            try:
                await asyncio.wait_for(self.connect(), timeout=2.0)
            except Exception as e:
                raise DatabaseUnavailableError(f"Database unavailable: {e}") from e

        # Prepare unnest arrays
        ids = list(multipliers_dict.keys())
        mults = list(multipliers_dict.values())
        
        query = """
        UPDATE ways AS w
        SET cost = w.length_m * m.multiplier
        FROM unnest($1::bigint[], $2::float[]) AS m(id, multiplier)
        WHERE w.gid = m.id
        """
        try:
            async with self.pool.acquire() as conn:
                await asyncio.wait_for(conn.execute(query, ids, mults), timeout=5.0)
        except (PostgresConnectionError, CannotConnectNowError, asyncio.TimeoutError, TimeoutError, OSError, InterfaceError) as e:
            self.pool = None
            logger.error(f"Database error during apply_multipliers: {e}")
            raise DatabaseUnavailableError(f"Database unavailable during apply_multipliers: {e}") from e

    async def decay_multipliers(self):
        """
        Asymptotically decay congested edge costs: cost = max(length_m, cost * 0.95).
        Prevents dead workers from leaving edges permanently penalized.
        """
        if not self.pool:
            try:
                await asyncio.wait_for(self.connect(), timeout=2.0)
            except Exception as e:
                raise DatabaseUnavailableError(f"Database unavailable: {e}") from e

        query = """
        UPDATE ways 
        SET cost = GREATEST(length_m, cost * 0.95)
        WHERE cost > length_m
        """
        try:
            async with self.pool.acquire() as conn:
                await asyncio.wait_for(conn.execute(query), timeout=5.0)
        except (PostgresConnectionError, CannotConnectNowError, asyncio.TimeoutError, TimeoutError, OSError, InterfaceError) as e:
            self.pool = None
            logger.error(f"Database error during decay_multipliers: {e}")
            raise DatabaseUnavailableError(f"Database unavailable during decay_multipliers: {e}") from e

    async def get_multipliers(self):
        if not self.pool:
            try:
                await asyncio.wait_for(self.connect(), timeout=2.0)
            except Exception as e:
                raise DatabaseUnavailableError(f"Database unavailable: {e}") from e

        query = "SELECT gid as id, cost / NULLIF(length_m, 0) as multiplier FROM ways"
        try:
            async with self.pool.acquire() as conn:
                records = await asyncio.wait_for(conn.fetch(query), timeout=5.0)
                return {r['id']: r['multiplier'] for r in records if r['multiplier'] is not None}
        except (PostgresConnectionError, CannotConnectNowError, asyncio.TimeoutError, TimeoutError, OSError, InterfaceError) as e:
            self.pool = None
            logger.error(f"Database error during get_multipliers: {e}")
            raise DatabaseUnavailableError(f"Database unavailable during get_multipliers: {e}") from e

    async def reset_multipliers(self):
        if not self.pool:
            try:
                await asyncio.wait_for(self.connect(), timeout=2.0)
            except Exception as e:
                raise DatabaseUnavailableError(f"Database unavailable: {e}") from e

        query = "UPDATE ways SET cost = length_m"
        try:
            async with self.pool.acquire() as conn:
                await asyncio.wait_for(conn.execute(query), timeout=5.0)
        except (PostgresConnectionError, CannotConnectNowError, asyncio.TimeoutError, TimeoutError, OSError, InterfaceError) as e:
            self.pool = None
            logger.error(f"Database error during reset_multipliers: {e}")
            raise DatabaseUnavailableError(f"Database unavailable during reset_multipliers: {e}") from e
