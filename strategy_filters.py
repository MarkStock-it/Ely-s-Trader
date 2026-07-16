"""Deterministic market-condition filters for directional strategies."""
import math


def market_regime(df, cfg) -> str:
    period = int(cfg.get("REGIME_EMA_PERIOD", 50))
    if len(df) < period:
        return "insufficient_data"
    ema = df.close.ewm(span=period, adjust=False).mean()
    slope = (ema.iloc[-1] / ema.iloc[-min(10, len(ema))] - 1)
    threshold = float(cfg.get("REGIME_MIN_SLOPE", 0.002))
    if slope > threshold: return "bull_trend"
    if slope < -threshold: return "bear_trend"
    return "sideways"


def signal_allowed(df, signal: str, cfg):
    regime = market_regime(df, cfg)
    if cfg.get("REGIME_FILTER_ENABLED", True):
        if signal == "buy" and regime != "bull_trend": return False, regime, "regime"
        if signal == "sell": return False, regime, "spot bot is long-only"
    lookback = int(cfg.get("FILTER_LOOKBACK", 20))
    if len(df) < lookback: return False, regime, "insufficient filter data"
    volume_mean = float(df.volume.iloc[-lookback:].mean())
    if volume_mean <= 0 or float(df.volume.iloc[-1]) < volume_mean * float(cfg.get("MIN_VOLUME_RATIO", 0.8)):
        return False, regime, "low volume"
    returns = df.close.pct_change().iloc[-lookback:]
    volatility = float(returns.std())
    if not math.isfinite(volatility) or volatility < float(cfg.get("MIN_VOLATILITY", 0.0002)):
        return False, regime, "volatility too low"
    if volatility > float(cfg.get("MAX_VOLATILITY", 0.05)):
        return False, regime, "volatility too high"
    return True, regime, "OK"
