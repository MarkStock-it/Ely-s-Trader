"""Simple observability initializer (Sentry optional).

Call `init_observability(cfg)` during startup to enable Sentry (if configured).
"""
import os
import logging
logger = logging.getLogger("mega_trading_bot.observability")
from alerts import alerts


def init_observability(cfg: dict | None = None):
    cfg = cfg or {}
    sentry_dsn = os.environ.get("SENTRY_DSN") or cfg.get("SENTRY_DSN")
    if not sentry_dsn:
        logger.debug("Sentry DSN not configured; skipping Sentry init")
        return False
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=sentry_dsn, traces_sample_rate=float(cfg.get("SENTRY_TRACES_SAMPLE_RATE", 0.0)))
        logger.info("Sentry initialized")
        return True
    except Exception:
        logger.exception("Failed to initialize Sentry")
        try:
            alerts.send_slack("Sentry init failed for mega_trading_bot")
        except Exception:
            pass
        return False
