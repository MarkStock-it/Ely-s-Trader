import os
import sys
import tempfile
# Ensure parent directory is on sys.path so tests can import package modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import safety


def test_validate_config_ok():
    cfg = {"EXCHANGE": "binance", "SYMBOL": "BTCUSDT", "PAPER_MODE": True, "LIVE_MODE": False, "DATA_PATH": "."}
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
    import time
    time.sleep(1.1)
    assert cb.allow()


def test_live_requires_native_protective_stops():
    cfg = {"EXCHANGE": "binance", "SYMBOL": "BTCUSDT", "PAPER_MODE": False,
           "LIVE_MODE": True, "DATA_PATH": ".", "API_KEY": "x", "API_SECRET": "y"}
    try:
        safety.validate_config(cfg)
        assert False, "Expected native-stop validation failure"
    except ValueError as exc:
        assert "protective stops" in str(exc)


def test_non_spot_trading_mode_is_rejected():
    cfg = {"EXCHANGE": "binance", "SYMBOL": "BTCUSDT", "PAPER_MODE": True,
           "LIVE_MODE": False, "DATA_PATH": ".", "TRADING_MODE": "futures"}
    try:
        safety.validate_config(cfg)
        assert False, "Expected spot-only validation failure"
    except ValueError as exc:
        assert "must be spot" in str(exc)
