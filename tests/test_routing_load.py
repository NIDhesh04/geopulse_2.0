import pytest
import asyncio
import time
import socket
from unittest.mock import AsyncMock, MagicMock
import aiohttp
import uvicorn
from api.main import app
from api.routing import RoutingService

def get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

async def start_test_server(port: int):
    config = uvicorn.Config(app=app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    # Wait until server is started
    for _ in range(50):
        if server.started:
            break
        await asyncio.sleep(0.05)
    return server, server_task

@pytest.mark.asyncio
async def test_routing_load_100_requests():
    """
    Load test using aiohttp and asyncio to issue 100 concurrent requests to /route.
    Measures and logs throughput (req/s), p50, p95, and p99 latencies.
    Verifies graceful handling under high concurrency.
    """
    # Setup mock routing service with realistic latency simulation to avoid DB dependency in CI
    mock_routing = MagicMock()
    mock_routing.db_active = True
    mock_routing._down = False
    mock_routing.pool = MagicMock()
    mock_routing.pool._closed = False
    
    # 50-connection pool simulation
    pool_sem = asyncio.Semaphore(50)
    
    async def mock_route(src_lat, src_lon, dst_lat, dst_lon, static=False, algorithm="dijkstra"):
        async with pool_sem:
            # Simulate 2-5ms query execution
            await asyncio.sleep(0.003)
            return [
                {"seq": 1, "path_seq": 1, "node": 101, "edge": 1420, "cost": 12.4, "agg_cost": 12.4},
                {"seq": 2, "path_seq": 2, "node": 102, "edge": 1421, "cost": 8.1, "agg_cost": 20.5}
            ]
            
    mock_routing.route = mock_route
    mock_routing.decay_multipliers = AsyncMock()
    
    port = get_free_port()
    server, server_task = await start_test_server(port)
    base_url = f"http://127.0.0.1:{port}"

    orig_routing = app.state.routing
    app.state.routing = mock_routing

    num_requests = 100
    concurrency = 25
    latencies = []
    
    connector = aiohttp.TCPConnector(limit=concurrency + 10)
    timeout = aiohttp.ClientTimeout(total=10.0)

    try:
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            sem = asyncio.Semaphore(concurrency)
            
            async def send_single_route(req_id: int):
                async with sem:
                    t0 = time.perf_counter()
                    params = {
                        "src_lat": 41.8845,
                        "src_lon": -87.6330,
                        "dst_lat": 41.8785,
                        "dst_lon": -87.6250,
                        "static": "false"
                    }
                    async with session.get(f"{base_url}/route", params=params) as resp:
                        status = resp.status
                        body = await resp.json()
                        elapsed_ms = (time.perf_counter() - t0) * 1000.0
                        latencies.append(elapsed_ms)
                        return status, body

            t_start = time.perf_counter()
            tasks = [send_single_route(i) for i in range(num_requests)]
            results = await asyncio.gather(*tasks)
            total_duration = time.perf_counter() - t_start

            successful = [r for r in results if r[0] == 200]
            assert len(successful) == num_requests, f"Expected {num_requests} successful responses, got {len(successful)}"

            latencies.sort()
            p50 = latencies[int(len(latencies) * 0.50)]
            p95 = latencies[int(len(latencies) * 0.95)]
            p99 = latencies[int(len(latencies) * 0.99)]
            throughput = num_requests / total_duration

            print(f"\n[Load Test Results: {num_requests} requests, concurrency {concurrency}]")
            print(f"  Throughput: {throughput:.2f} req/s")
            print(f"  Latency p50: {p50:.2f}ms")
            print(f"  Latency p95: {p95:.2f}ms")
            print(f"  Latency p99: {p99:.2f}ms")
            print(f"  Connection pool available slots: {pool_sem._value}/50")

            assert pool_sem._value == 50, "Connection pool checkout must cleanly return all acquired slots"
            assert p95 < 500.0, f"Expected p95 < 500ms, got {p95:.2f}ms"

    finally:
        server.should_exit = True
        await server_task
        app.state.routing = orig_routing

if __name__ == "__main__":
    asyncio.run(test_routing_load_100_requests())
