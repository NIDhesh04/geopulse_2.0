import pytest
import time
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)

@pytest.mark.unit
def test_metrics_endpoint_schema():
    response = client.get("/metrics")
    assert response.status_code == 200
    data = response.json()
    
    # Assert exact schema keys from spec Section 4B + uptime
    required_keys = {"pings_in", "pings_rejected", "stream_lag", "worker_last_tick", "worker_healthy", "uptime_seconds"}
    assert required_keys.issubset(data.keys()), f"Missing keys in /metrics: {required_keys - set(data.keys())}"
    assert isinstance(data["pings_in"], int)
    assert isinstance(data["pings_rejected"], int)
    assert isinstance(data["stream_lag"], int)
    assert isinstance(data["worker_healthy"], bool)
    assert isinstance(data["uptime_seconds"], int)

@pytest.mark.unit
def test_health_check_missing_heartbeat(monkeypatch):
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value=None)
    app.state.redis = mock_redis

    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["worker"] == "missing_heartbeat"

@pytest.mark.unit
def test_health_check_stale_heartbeat(monkeypatch):
    # Stale heartbeat (older than 60s)
    stale_time = time.time() - 100
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value=str(stale_time))
    app.state.redis = mock_redis

    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["worker"] == "stale_heartbeat"

@pytest.mark.unit
def test_health_check_healthy_heartbeat(monkeypatch):
    # Fresh heartbeat (within last 10s)
    fresh_time = time.time() - 5
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value=str(fresh_time))
    app.state.redis = mock_redis

    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
