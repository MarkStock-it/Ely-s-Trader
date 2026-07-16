import pandas as pd

from risk import cap_quantity, entry_guard
from strategy_filters import market_regime, signal_allowed


def frame(prices, volumes=None):
    return pd.DataFrame({"close": prices, "volume": volumes or [100] * len(prices)})


def test_quantity_is_capped_by_cash_and_exchange():
    assert cap_quantity(100, 1000, 100, .01) < 10
    assert cap_quantity(100, 1000, 100, 0, exchange_max=3) == 3


def test_portfolio_risk_limits():
    cfg = {"DAILY_LOSS_LIMIT": .03, "MAX_DRAWDOWN": .10, "MAX_AGGREGATE_RISK": .03}
    assert not entry_guard(equity=960, initial_equity=1000, day_start_equity=1000,
                           proposed_risk=1, existing_risks=[], cfg=cfg).allowed
    assert not entry_guard(equity=1000, initial_equity=1000, day_start_equity=1000,
                           proposed_risk=20, existing_risks=[20], cfg=cfg).allowed


def test_regime_volume_and_volatility_filters():
    prices = [100 + i for i in range(60)]
    cfg = {"REGIME_EMA_PERIOD": 20, "REGIME_MIN_SLOPE": .001,
           "FILTER_LOOKBACK": 20, "MIN_VOLUME_RATIO": .8,
           "MIN_VOLATILITY": .00001, "MAX_VOLATILITY": .1}
    data = frame(prices)
    assert market_regime(data, cfg) == "bull_trend"
    assert signal_allowed(data, "buy", cfg)[0]
    data.loc[data.index[-1], "volume"] = 1
    assert signal_allowed(data, "buy", cfg)[2] == "low volume"
