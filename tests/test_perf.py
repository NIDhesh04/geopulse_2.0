import pytest
import time
import asyncio
import websockets
import json

@pytest.mark.perf
@pytest.mark.asyncio
async def test_websocket_ingestion_throughput():
    uri = "ws://localhost:8000/ws/ingest"
    num_pings = 1000
    
    start_time = time.time()
    
    async def send_pings():
        try:
            async with websockets.connect(uri) as ws:
                for i in range(num_pings):
                    ping = {
                        "vehicle_id": f"v_{i}",
                        "lat": 41.88,
                        "lon": -87.62,
                        "speed_kmh": 30.0,
                        "ts": int(time.time())
                    }
                    await ws.send(json.dumps(ping))
        except Exception as e:
            pytest.skip(f"Could not connect to API for perf test: {e}")

    await send_pings()
    duration = time.time() - start_time
    throughput = num_pings / duration
    
    print(f"\n[Performance] WebSocket Ingestion Throughput: {throughput:.2f} pings/sec")
    # No assert, just printing throughput baseline
