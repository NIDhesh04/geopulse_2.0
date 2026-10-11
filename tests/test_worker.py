import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from worker.main import CongestionWorker

@pytest.fixture
def mock_routing_service():
    routing = MagicMock()
    routing.connect = AsyncMock()
    routing.snap_to_edge = AsyncMock(return_value={'id': 'edge_1'})
    routing.apply_multipliers = AsyncMock()
    return routing

@pytest.mark.unit
@pytest.mark.asyncio
async def test_worker_process_batch(mock_routing_service, monkeypatch):
    # Mock Redis XACK and HSET
    mock_redis = MagicMock()
    mock_redis.xack = AsyncMock()
    mock_redis.xadd = AsyncMock()
    mock_redis.hset = AsyncMock()
    mock_redis.set = AsyncMock()
    
    monkeypatch.setattr("redis.asyncio.from_url", lambda url, **kwargs: mock_redis)
    
    worker = CongestionWorker(mock_routing_service, "redis://mock")
    worker.r = mock_redis
    
    messages = [
        ("1234-0", {
            "vehicle_id": "v1", "lat": "41.88", "lon": "-87.62", "speed_kmh": "10.0", "ts": "1000"
        })
    ]
    
    await worker.process_batch(messages)
    
    # Assert routing was called
    mock_routing_service.snap_to_edge.assert_called_once_with(41.88, -87.62)
    mock_routing_service.apply_multipliers.assert_called_once()
    
    # Assert bulk HSET was called for vehicles:latest
    mock_redis.hset.assert_called_once()
    args, kwargs = mock_redis.hset.call_args
    assert args[0] == "vehicles:latest"
    assert "v1" in kwargs["mapping"]
    
    # Assert XACK was called
    mock_redis.xack.assert_called_once_with(worker.stream_name, worker.group_name, "1234-0")
