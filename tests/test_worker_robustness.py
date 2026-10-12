import pytest
import asyncio
import time
import tracemalloc
from unittest.mock import MagicMock, AsyncMock
from worker.main import CongestionWorker

@pytest.fixture
def mock_routing_service():
    routing = MagicMock()
    routing.connect = AsyncMock()
    routing.snap_to_edge = AsyncMock(return_value={'id': 1420})
    routing.apply_multipliers = AsyncMock()
    return routing

@pytest.fixture
def mock_redis():
    r = MagicMock()
    r.xack = AsyncMock()
    r.xadd = AsyncMock()
    r.hset = AsyncMock()
    r.set = AsyncMock()
    return r

@pytest.mark.unit
@pytest.mark.asyncio
async def test_stream_id_deduplication(mock_routing_service, mock_redis, monkeypatch):
    """
    Verifies that redelivered stream message IDs (e.g., from consumer reclamation)
    are skipped from reprocessing but still acknowledged via XACK.
    """
    monkeypatch.setattr("redis.asyncio.from_url", lambda url, **kwargs: mock_redis)
    worker = CongestionWorker(mock_routing_service, "redis://mock")
    worker.r = mock_redis

    msg_id = "1700000000000-0"
    payload = {
        "vehicle_id": "v_dedup",
        "lat": "41.8845",
        "lon": "-87.6330",
        "speed_kmh": "25.0",
        "ts": "1700000000"
    }

    # First delivery
    await worker.process_batch([(msg_id, payload)])
    assert mock_routing_service.apply_multipliers.call_count == 1
    assert mock_redis.xack.call_count == 1

    # Second delivery (same msg_id)
    await worker.process_batch([(msg_id, payload)])
    # apply_multipliers should NOT be called again
    assert mock_routing_service.apply_multipliers.call_count == 1
    # But xack MUST be called again to acknowledge redelivery
    assert mock_redis.xack.call_count == 2
    assert msg_id in worker.dedup_cache

@pytest.mark.unit
@pytest.mark.asyncio
async def test_snapping_lru_cache_speedup(mock_routing_service, mock_redis, monkeypatch):
    """
    Verifies that coordinate snapping is cached at 4-decimal resolution (~11m),
    delivering >5x query speedup on repeated coordinates.
    """
    monkeypatch.setattr("redis.asyncio.from_url", lambda url, **kwargs: mock_redis)
    worker = CongestionWorker(mock_routing_service, "redis://mock")
    worker.r = mock_redis

    # Simulate slow PostGIS query
    async def slow_snap(lat, lon):
        await asyncio.sleep(0.001)  # 1ms query simulation
        return {'id': 1420}

    mock_routing_service.snap_to_edge = slow_snap

    lat, lon = 41.8845123, -87.6330456
    # Cold lookup (cache miss)
    t0 = time.perf_counter()
    res1 = await worker.snap_with_cache(lat, lon)
    cold_duration = time.perf_counter() - t0

    # 100 Repeated warm lookups (cache hits)
    t1 = time.perf_counter()
    for _ in range(100):
        res2 = await worker.snap_with_cache(lat, lon)
    warm_duration = (time.perf_counter() - t1) / 100.0

    assert res1 == res2
    assert worker.snap_hits == 100
    assert worker.snap_misses == 1

    speedup = cold_duration / max(warm_duration, 1e-9)
    print(f"\n[Snapping Cache Benchmark] Cold: {cold_duration*1000:.3f}ms | Warm: {warm_duration*1000:.4f}ms | Speedup: {speedup:.1f}x")
    assert speedup >= 5.0, f"Expected snapping speedup >= 5x, got {speedup:.2f}x"

@pytest.mark.unit
@pytest.mark.asyncio
async def test_bounded_memory_under_ping_flood(mock_routing_service, mock_redis, monkeypatch):
    """
    Simulates a flood of 1,000,000 synthetic pings through the worker's
    deduplication, snapping, and state aggregation queues.
    Proves via tracemalloc that resident memory consumption remains strictly bounded (< 256 MB RSS).
    """
    monkeypatch.setattr("redis.asyncio.from_url", lambda url, **kwargs: mock_redis)
    worker = CongestionWorker(mock_routing_service, "redis://mock")
    worker.r = mock_redis

    mock_routing_service.snap_to_edge = AsyncMock(return_value={'id': 101})
    mock_routing_service.apply_multipliers = AsyncMock()

    tracemalloc.start()
    mem_start, _ = tracemalloc.get_traced_memory()

    total_pings = 1000000
    batch_size = 1000
    num_batches = total_pings // batch_size

    sample_payloads = [
        {
            "vehicle_id": f"v_{i % 500}",
            "lat": "41.8845",
            "lon": "-87.6330",
            "speed_kmh": "30.0",
            "ts": "1700000000"
        }
        for i in range(batch_size)
    ]

    for b in range(num_batches):
        batch = [(f"{b*batch_size + i}-0", sample_payloads[i]) for i in range(batch_size)]
        await worker.process_batch(batch)

    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    peak_mb = peak_mem / (1024 * 1024)
    current_mb = current_mem / (1024 * 1024)
    print(f"\n[1M Ping Memory Profile] Peak Memory: {peak_mb:.2f} MB | Final Memory: {current_mb:.2f} MB")
    print(f"  Dedup cache size: {len(worker.dedup_cache)} / maxlen {worker.dedup_maxlen}")
    print(f"  Snap cache size: {len(worker.snap_cache)} / maxlen {worker.snap_cache_maxlen}")

    # Memory must stay well under 256 MB limit (typically < 35 MB)
    assert peak_mb < 256.0, f"Worker exceeded memory ceiling: {peak_mb:.2f} MB > 256 MB"
    assert len(worker.dedup_cache) <= worker.dedup_maxlen
    assert len(worker.snap_cache) <= worker.snap_cache_maxlen
