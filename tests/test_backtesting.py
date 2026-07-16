import json

import pandas as pd
import pytest

from backtesting.comparison import compare_strategies
from backtesting.data_loader import load_csv, validate_ohlcv
from backtesting.engine import BacktestEngine
from backtesting.metrics import calculate_metrics
from backtesting.models import BacktestConfig
from backtesting.reports import export_csv, export_json
from backtesting.validation import non_overlapping_evaluation, walk_forward


def candles(prices=(100, 100, 110, 110)):
    return pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=len(prices), freq="h"),
        "open": prices, "high": [p * 1.02 for p in prices], "low": [p * .98 for p in prices],
        "close": prices, "volume": [10] * len(prices)})


def once_buy(window): return "buy" if len(window) == 1 else None


@pytest.mark.parametrize("change,match", [
    (lambda d: d.drop(columns="volume"), "Missing"),
    (lambda d: d.assign(close="bad"), "numeric"),
    (lambda d: d.assign(low=0), "greater than zero"),
    (lambda d: d.assign(volume=-1), "must not be negative")])
def test_validation(change, match):
    with pytest.raises(ValueError, match=match): validate_ohlcv(change(candles()))


def test_duplicate_and_unordered_rejected():
    d = candles(); d.loc[1, "timestamp"] = d.loc[0, "timestamp"]
    with pytest.raises(ValueError, match="Duplicate"): validate_ohlcv(d)
    with pytest.raises(ValueError, match="ordered"): validate_ohlcv(candles().iloc[::-1])
    with pytest.warns(UserWarning): assert validate_ohlcv(candles().iloc[::-1], sort_unordered=True).timestamp.is_monotonic_increasing


def test_future_is_hidden_and_next_open_execution():
    seen = []
    def strategy(window): seen.append(len(window)); return "buy" if len(window) == 1 else None
    result = BacktestEngine(candles((100, 120, 130)), BacktestConfig()).run(strategy)
    assert seen == [1, 2, 3]
    assert result.trades[0].entry_market_price == 120


@pytest.mark.parametrize("field", ["fee_rate", "spread_rate", "slippage_rate"])
def test_costs_reduce_results(field):
    base = BacktestEngine(candles(), BacktestConfig(fee_rate=0, spread_rate=0, slippage_rate=0)).run(once_buy)
    costly = BacktestEngine(candles(), BacktestConfig(**{field: .01})).run(once_buy)
    assert costly.metrics["ending_equity"] < base.metrics["ending_equity"]


def test_insufficient_cash_or_minimum_blocks_entry():
    r = BacktestEngine(candles(), BacktestConfig(minimum_position_size=1000)).run(once_buy)
    assert r.metrics["total_trades"] == 0


def test_exit_without_holdings_is_blocked():
    r = BacktestEngine(candles(), BacktestConfig()).run(lambda window: "sell")
    assert r.metrics["total_trades"] == 0


@pytest.mark.parametrize("kwargs,reason", [({"stop_loss_pct": .05}, "stop_loss"), ({"take_profit_pct": .05}, "take_profit")])
def test_intrabar_exits(kwargs, reason):
    d = candles((100, 100, 100)); d.loc[1:, "high"] = 110; d.loc[1:, "low"] = 90
    r = BacktestEngine(d, BacktestConfig(**kwargs)).run(once_buy)
    assert r.trades[0].exit_reason == reason


def test_both_touched_is_stop_first_and_net_includes_fees():
    d = candles((100, 100, 100)); d.loc[1:, "high"] = 110; d.loc[1:, "low"] = 90
    r = BacktestEngine(d, BacktestConfig(stop_loss_pct=.05, take_profit_pct=.05)).run(once_buy)
    t = r.trades[0]
    assert t.exit_reason == "stop_loss"
    assert t.net_profit == pytest.approx(t.gross_profit - t.entry_fee - t.exit_fee)


def test_drawdown_profit_factor_expectancy_and_empty():
    class T:
        def __init__(self, p): self.net_profit=p; self.entry_fee=self.exit_fee=0; self.holding_duration=1
    eq=[{"timestamp":0,"drawdown":0,"drawdown_percentage":0},{"timestamp":1,"drawdown":20,"drawdown_percentage":20}]
    m=calculate_metrics(100,110,[T(20),T(-10)],eq,100,120)
    assert m["profit_factor"] == 2 and m["expectancy"] == 5 and m["maximum_drawdown_amount"] == 20
    empty=BacktestEngine(candles(),BacktestConfig()).run(lambda w: None)
    assert empty.metrics["total_trades"] == 0 and empty.metrics["sharpe_ratio"] == 0
    assert empty.metrics["buy_and_hold_return"] == pytest.approx(10)


def test_exports_and_comparison(tmp_path):
    r=BacktestEngine(candles(),BacktestConfig()).run(once_buy)
    jp, cp = tmp_path/"r.json", tmp_path/"r.csv"
    export_json(r,str(jp)); export_csv(r,str(cp))
    assert json.loads(jp.read_text())["metrics"]["total_trades"] == 1
    assert "trades" in cp.read_text()
    ranked=compare_strategies(candles(),BacktestConfig(),{"few": once_buy, "none": lambda w: None}, minimum_trades=5)
    assert all(row["result"].metadata["candles"] == 4 for row in ranked)
    assert ranked[0]["composite_score"] < 100


def test_multi_market_and_walk_forward_are_non_overlapping():
    data = candles((100, 101, 102, 103, 104, 105, 106, 107))
    cases = [{"symbol": "BTC/USDT", "timeframe": "1h", "period": "A", "data": data},
             {"symbol": "ETH/USDT", "timeframe": "4h", "period": "B", "data": data.copy()}]
    results = non_overlapping_evaluation(cases, BacktestConfig(), once_buy)
    assert [(x["symbol"], x["timeframe"]) for x in results] == [("BTC/USDT", "1h"), ("ETH/USDT", "4h")]
    windows = walk_forward(data, BacktestConfig(), once_buy, 4, 2)
    assert windows and all(x["train_end"] < x["test_start"] for x in windows)
