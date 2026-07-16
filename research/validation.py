from datetime import datetime, timedelta, timezone
import uuid

from .schemas import utc

FATAL = {"lookahead", "data_leakage", "invalid_data", "insufficient_data", "execution_failed"}

def risk_multiplier(confidence, threshold, minimum):
    if confidence < threshold: return 0.0
    if threshold >= 1: return min(1.0, max(0.0, minimum))
    scaled = minimum + (confidence - threshold) / (1 - threshold) * (1 - minimum)
    return min(1.0, max(0.0, scaled))

def validate_result(request, result, fingerprint, cfg, now=None):
    now = now or datetime.now(timezone.utc); tolerance = timedelta(seconds=int(cfg.get("RESEARCH_CLOCK_TOLERANCE_SECONDS", 300)))
    if result.request_id != request.request_id or result.strategy_id != request.strategy_id: raise ValueError("request or strategy mismatch")
    norm = lambda x: str(x).upper().replace("/", "").replace("-", "")
    if norm(result.symbol) != norm(request.symbol): raise ValueError("symbol mismatch")
    if result.timeframe != request.timeframe: raise ValueError("timeframe mismatch")
    if result.direction != "long": raise ValueError("direction mismatch")
    if result.configuration_fingerprint != fingerprint: raise ValueError("configuration fingerprint mismatch")
    generated = utc(result.generated_at)
    if generated > now + tolerance: raise ValueError("future-dated research")
    max_age = timedelta(seconds=int(cfg.get("RESEARCH_MAX_AGE_SECONDS", 86400)))
    if generated < now - max_age: raise ValueError("stale research")
    fatal = [w for w in result.warnings if str(w).lower() in FATAL]
    if fatal: raise ValueError("fatal research warnings: " + ", ".join(fatal))
    m = result.out_of_sample_metrics; confidence = float(result.confidence)
    if m["trade_count"] < request.minimum_oos_trades: raise ValueError("insufficient OOS trades")
    if float(m["expectancy"]) <= request.minimum_expectancy: raise ValueError("nonpositive/insufficient expectancy")
    if float(m["maximum_drawdown_percentage"]) > request.maximum_drawdown: raise ValueError("excessive OOS drawdown")
    if confidence < request.minimum_confidence: raise ValueError("confidence below threshold")
    if request.minimum_profit_factor is not None and float(m["profit_factor"]) < request.minimum_profit_factor: raise ValueError("profit factor below threshold")
    valid_from = max(now, generated); ttl = timedelta(seconds=int(cfg.get("RESEARCH_APPROVAL_TTL_SECONDS", 604800)))
    expires = valid_from + ttl; refresh = expires - timedelta(seconds=int(cfg.get("RESEARCH_REFRESH_LEAD_SECONDS", 86400)))
    multiplier = risk_multiplier(confidence, request.minimum_confidence, float(cfg.get("VIBETRADER_MIN_RISK_MULTIPLIER", .25)))
    return {"schema_version": 2, "approval_id": str(uuid.uuid4()), "request_id": request.request_id,
            "research_id": result.source_run_id, "strategy_id": request.strategy_id, "strategy_version": request.strategy_version,
            "configuration_fingerprint": fingerprint, "symbol": request.symbol, "timeframe": request.timeframe,
            "direction": "long", "confidence": confidence, "risk_multiplier": multiplier,
            "oos_metrics": m, "generated_at": result.generated_at, "valid_from": valid_from.isoformat(),
            "refresh_after": refresh.isoformat(), "expires_at": expires.isoformat(), "warnings": result.warnings,
            "limitations": result.limitations}
