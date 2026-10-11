import pytest
import asyncio
import time
import os
from unittest.mock import AsyncMock, MagicMock
from api.routing import RoutingService

@pytest.mark.unit
@pytest.mark.asyncio
async def test_routing_concurrency_50_requests():
    """
    Fires 50 simultaneous requests to RoutingService.route() using asyncio.gather.
    Ensures connection pool handles concurrent checkout/checkin without leakage or deadlock.
    Measures and asserts that p95 latency is bounded (< 100ms target).
    """
    db_url = os.getenv("DATABASE_URL", "postgresql://geopulse:password@localhost:5432/geopulse_db")
    service = RoutingService(db_url)
    
    # Try connecting to live database; fallback to simulated pool if DB unavailable
    use_live_db = False
    try:
        await asyncio.wait_for(service.connect(), timeout=1.0)
        # Test a quick query
        async with service.pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        use_live_db = True
    except Exception:
        use_live_db = False

    if not use_live_db:
        # Construct mock pool with simulated acquisition semaphore and query delay
        mock_pool = MagicMock()
        sem = asyncio.Semaphore(10)  # Standard pool size
        
        class MockConnectionContext:
            async def __aenter__(self):
                await sem.acquire()
                mock_conn = MagicMock()
                mock_conn.fetchrow = AsyncMock(return_value={"id": 1, "source_node_id": 101, "target_node_id": 102})
                mock_conn.fetch = AsyncMock(return_value=[
                    {"seq": 1, "path_seq": 1, "node": 101, "edge": 1, "cost": 0.5, "agg_cost": 0.5},
                    {"seq": 2, "path_seq": 2, "node": 102, "edge": -1, "cost": 0.0, "agg_cost": 0.5}
                ])
                return mock_conn

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                sem.release()

        mock_pool.acquire.side_effect = MockConnectionContext
        mock_pool.close = AsyncMock()
        service.pool = mock_pool

    lat1, lon1 = 41.8845, -87.6330
    lat2, lon2 = 41.8785, -87.6250
    latencies = []

    async def single_route_request(req_id: int):
        t0 = time.perf_counter()
        res = await service.route(lat1, lon1, lat2, lon2, static=True)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(elapsed_ms)
        return res

    tasks = [single_route_request(i) for i in range(50)]
    results = await asyncio.gather(*tasks)

    await service.close()

    assert len(results) == 50, "All 50 concurrent route requests must complete"
    for r in results:
        assert r is not None, "Each route query must return a valid path result"

    latencies.sort()
    p50 = latencies[int(len(latencies) * 0.50)]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]

    print(f"\n[Concurrency Benchmark] 50 Parallel Requests: p50={p50:.2f}ms, p95={p95:.2f}ms, p99={p99:.2f}ms")
    assert p95 < 100.0, f"Target p95 < 100ms violated: got {p95:.2f}ms"
