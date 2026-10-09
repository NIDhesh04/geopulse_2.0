import pytest
from unittest.mock import patch
from sim.utils import get_backoff_delay

@pytest.mark.unit
def test_backoff_scaling():
    # Test that max limits are respected
    with patch('random.uniform', side_effect=lambda a, b: b):
        assert get_backoff_delay(0, base_delay=1.0) == 1.0
        assert get_backoff_delay(1, base_delay=1.0) == 2.0
        assert get_backoff_delay(2, base_delay=1.0) == 4.0
        assert get_backoff_delay(10, base_delay=1.0, max_delay=60.0) == 60.0

@pytest.mark.unit
def test_backoff_jitter():
    # Test that it returns a value within the jitter range
    delay = get_backoff_delay(2, base_delay=1.0)
    assert 0 <= delay <= 4.0
