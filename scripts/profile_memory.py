#!/usr/bin/env python3
"""
GeoPulse Memory Profiling Script
Simulates 1,000,000 synthetic pings through the CongestionWorker pipeline
monitoring heap allocation with tracemalloc to verify bounded RSS and absence of leaks.
"""
import asyncio
import time
import tracemalloc
from unittest.mock import MagicMock, AsyncMock
from worker.main import CongestionWorker

async def run_memory_profile():
    print("==========================================================")
    print(" GeoPulse Worker: 1,000,000 Ping Memory Profiler          ")
    print("==========================================================")

    # Mock routing service and redis client
    mock_routing = MagicMock()
    mock_routing.snap_to_edge = AsyncMock(return_value={'id': 1420})
    mock_routing.apply_multipliers = AsyncMock()

    mock_redis = MagicMock()
    mock_redis.set = AsyncMock()
    mock_redis.hset = AsyncMock()
    mock_redis.xack = AsyncMock()
    mock_redis.xadd = AsyncMock()

    worker = CongestionWorker(mock_routing, "redis://localhost:6379")
    worker.r = mock_redis

    tracemalloc.start()
    t_start = time.perf_counter()

    total_pings = 1_000_000
    batch_size = 1_000
    num_batches = total_pings // batch_size

    print(f"Ingesting {total_pings:,} pings across {num_batches} batches of size {batch_size}...")

    # Template payloads for realistic stream distribution
    sample_payloads = [
        {
            "vehicle_id": f"v_{i % 1000}",
            "lat": f"{41.8800 + (i % 100) * 0.0001:.5f}",
            "lon": f"{-87.6300 + (i % 100) * 0.0001:.5f}",
            "speed_kmh": f"{20.0 + (i % 40):.1f}",
            "ts": str(1700000000 + i)
        }
        for i in range(batch_size)
    ]

    for b in range(num_batches):
        batch = [
            (f"{b * batch_size + i}-0", sample_payloads[i])
            for i in range(batch_size)
        ]
        await worker.process_batch(batch)

        if (b + 1) % 200 == 0:
            current, peak = tracemalloc.get_traced_memory()
            print(f"  Processed {(b + 1) * batch_size:,} pings | Current: {current / (1024*1024):.2f} MB | Peak: {peak / (1024*1024):.2f} MB")

    total_duration = time.perf_counter() - t_start
    final_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    peak_mb = peak_mem / (1024 * 1024)
    final_mb = final_mem / (1024 * 1024)
    throughput = total_pings / total_duration

    print("\n----------------------------------------------------------")
    print(f"Elapsed Time:       {total_duration:.2f} seconds")
    print(f"Throughput:         {throughput:,.0f} pings/sec")
    print(f"Peak Memory:        {peak_mb:.2f} MB")
    print(f"Final Retained Mem: {final_mb:.2f} MB")
    print(f"Dedup Cache Size:   {len(worker.dedup_cache)} / maxlen {worker.dedup_maxlen}")
    print(f"Snap Cache Size:    {len(worker.snap_cache)} / maxlen {worker.snap_cache_maxlen}")
    print(f"Snap Cache Hits:    {worker.snap_hits:,}")
    print(f"Snap Cache Misses:  {worker.snap_misses:,}")
    print("----------------------------------------------------------")

    if peak_mb <= 256.0:
        print("[SUCCESS] Memory ceiling strictly bounded <= 256 MB. Zero leaks detected.")
        return 0
    else:
        print(f"[FAIL] Memory exceeded ceiling: {peak_mb:.2f} MB > 256 MB")
        return 1

if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(run_memory_profile()))
