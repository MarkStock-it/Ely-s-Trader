"""safety.py

Helpers for safety, circuit breakers, kill-switches, and config validation.
"""
import os
import time
import json
import logging
from typing import Dict, Any

logger = logging.getLogger("mega_trading_bot.safety")


def validate_config(cfg: Dict[str, Any]) -> None:
    """Basic validation of critical configuration keys; raises ValueError on error."""
    required = ["EXCHANGE", "SYMBOL", "PAPER_MODE", "LIVE_MODE", "DATA_PATH"]
    errors = []
    for k in required:
        if k not in cfg:
            errors.append(f"Missing config key: {k}")
    if not isinstance(cfg.get("PAPER_MODE", True), bool):
        errors.append("PAPER_MODE must be boolean")
    if not isinstance(cfg.get("LIVE_MODE", False), bool):
        errors.append("LIVE_MODE must be boolean")
    paper = cfg.get("PAPER_MODE")
    live = cfg.get("LIVE_MODE")
    if isinstance(paper, bool) and isinstance(live, bool) and paper == live:
        errors.append("Exactly one of PAPER_MODE and LIVE_MODE must be true")
    if live and not (cfg.get("API_KEY") and cfg.get("API_SECRET")):
        errors.append("LIVE_MODE requires both API_KEY and API_SECRET")
    if live and not cfg.get("NATIVE_PROTECTIVE_STOPS", False):
        errors.append("LIVE_MODE requires verified exchange-native protective stops")
    if str(cfg.get("TRADING_MODE", "spot")).lower() != "spot":
        errors.append("TRADING_MODE must be spot; margin, futures, and swaps are disabled")
    for key in ("RISK_PER_TRADE", "DAILY_LOSS_LIMIT", "MAX_DRAWDOWN", "MAX_AGGREGATE_RISK"):
        try:
            value = float(cfg.get(key, 0.01))
            if not 0 < value <= 1: errors.append(f"{key} must be in (0, 1]")
        except (TypeError, ValueError): errors.append(f"{key} must be numeric")
    for key in ("PAPER_FEE_RATE", "PAPER_SLIPPAGE_RATE", "PAPER_SPREAD_RATE"):
        try:
            if float(cfg.get(key, 0)) < 0:
                errors.append(f"{key} must be non-negative")
        except (TypeError, ValueError):
            errors.append(f"{key} must be numeric")
    if errors:
        raise ValueError("; ".join(errors))


class CircuitBreaker:
    """Simple circuit breaker tracking consecutive failures and disabling trading.

    Usage: call `cb.record_failure()` on critical failures; call `cb.record_success()` on success.
    Check `cb.allow()` before placing live trades.
    """
    def __init__(self, max_failures: int = 5, cooldown_seconds: int = 300):
        self.max_failures = int(max_failures)
        self.cooldown_seconds = int(cooldown_seconds)
        self.failures = 0
        self.last_failure_ts = 0

    def record_failure(self) -> None:
        self.failures += 1
        self.last_failure_ts = time.time()
        logger.warning("CircuitBreaker recorded failure %s/%s", self.failures, self.max_failures)

    def record_success(self) -> None:
        if self.failures > 0:
            logger.info("CircuitBreaker success; resetting failures")
        self.failures = 0

    def allow(self) -> bool:
        if self.failures >= self.max_failures:
            # check cooldown
            if time.time() - self.last_failure_ts > self.cooldown_seconds:
                logger.info("CircuitBreaker cooldown passed; allowing attempts")
                self.failures = 0
                return True
            logger.error("CircuitBreaker open: %s failures; in cooldown", self.failures)
            return False
        return True


def kill_switch_engaged(cfg: Dict[str, Any]) -> bool:
    """Check for a filesystem kill switch file to immediately stop trading.

    Create a file named STOP_TRADING in DATA_PATH to trigger.
    """
    data_path = cfg.get("DATA_PATH", "data")
    stop_file = os.path.join(data_path, "STOP_TRADING")
    try:
        return os.path.exists(stop_file)
    except Exception:
        return False


def read_persisted_guard(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Read persisted safety params from DATA_PATH/safety.json (non-critical).
    Returns a dict (may be empty).
    """
    data_path = cfg.get("DATA_PATH", "data")
    safe_file = os.path.join(data_path, "safety.json")
    try:
        if os.path.exists(safe_file):
            with open(safe_file, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        logger.exception("Failed to read safety.json")
    return {}
