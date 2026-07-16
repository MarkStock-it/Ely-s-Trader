import os
import sys
import tempfile
# Ensure parent directory is on sys.path so tests can import package modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import safety


def test_validate_config_ok():
    cfg = {"EXCHANGE": "binance", "SYMBOL": "BTCUSDT", "PAPER_MODE": True, "DATA_PATH": "."}
    safety.validate_config(cfg)


def test_validate_config_missing():
    cfg = {"EXCHANGE": "binance"}
    try:
        safety.validate_config(cfg)
        assert False, "Expected ValueError"
    except ValueError:
        assert True


def test_circuit_breaker():
    cb = safety.CircuitBreaker(max_failures=2, cooldown_seconds=1)
    assert cb.allow()
    cb.record_failure()
    assert cb.allow()
    cb.record_failure()
    assert not cb.allow()
    # wait for cooldown
    import time
    time.sleep(1.1)
    assert cb.allow()
