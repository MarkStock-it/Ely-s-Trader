from datetime import datetime, timezone
import uuid

from .schemas import ResearchRequest

def request_from_config(cfg, strategy_id=None, symbol=None, timeframe=None, request_id=None):
    return ResearchRequest(request_id=request_id or str(uuid.uuid4()), strategy_id=strategy_id or cfg.get("STRATEGY", "macd"),
        strategy_version=str(cfg.get("STRATEGY_VERSION", "1")), symbol=symbol or cfg.get("SYMBOL", "BTC/USDT"),
        timeframe=timeframe or cfg.get("INTERVAL", "1m"), direction="long",
        strategy_parameters={"atr_period": cfg.get("ATR_PERIOD", 14), "atr_multiplier": cfg.get("ATR_MULTIPLIER", 1.5),
                             "regime_ema_period": cfg.get("REGIME_EMA_PERIOD", 50), "regime_min_slope": cfg.get("REGIME_MIN_SLOPE", .002),
                             "min_volume_ratio": cfg.get("MIN_VOLUME_RATIO", .8), "min_volatility": cfg.get("MIN_VOLATILITY", .0002),
                             "max_volatility": cfg.get("MAX_VOLATILITY", .05)},
        risk_parameters={"risk_per_trade": cfg.get("RISK_PER_TRADE", .01), "max_aggregate_risk": cfg.get("MAX_AGGREGATE_RISK", .03),
                         "max_position_fraction": cfg.get("MAX_POSITION_FRACTION", 1)},
        execution_assumptions={"fee_rate": cfg.get("PAPER_FEE_RATE", .001), "spread_rate": cfg.get("PAPER_SPREAD_RATE", .0002),
                               "slippage_rate": cfg.get("PAPER_SLIPPAGE_RATE", .0005), "stop_loss": "ATR",
                               "take_profit": None, "execution_convention": "close signal; next candle open",
                               "intrabar_policy": "stop_first"},
        data_period=cfg.get("RESEARCH_DATA_PERIOD", {"identifier": "configured research dataset"}),
        minimum_oos_trades=int(cfg.get("VIBETRADER_MIN_OOS_TRADES", 20)),
        minimum_expectancy=float(cfg.get("VIBETRADER_MIN_EXPECTANCY", 0)),
        maximum_drawdown=float(cfg.get("VIBETRADER_MAX_OOS_DRAWDOWN_PCT", 15)),
        minimum_confidence=float(cfg.get("VIBETRADER_MIN_CONFIDENCE", .65)),
        minimum_profit_factor=cfg.get("VIBETRADER_MIN_PROFIT_FACTOR"), created_at=datetime.now(timezone.utc).isoformat())
