import json

import pandas as pd

from backtesting.models import BacktestConfig
from strategies import Action, Signal
from walkforward import QualificationRules, WalkForwardConfig, WalkForwardEngine
from walkforward.metrics import aggregate, stability
from walkforward.report import write_reports
from walkforward.splitter import split_windows


def candles(count=36):
    prices = [100 + i for i in range(count)]
    return pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=count, freq="D"),
        "open": prices, "high": [x + 1 for x in prices], "low": [x - 1 for x in prices],
        "close": prices, "volume": [100] * count})


def alternating(window):
    if len(window) == 1: return Signal(Action.BUY, 1, "start")
    if len(window) == 3: return Signal(Action.SELL, 1, "finish")
    return Signal(Action.HOLD, 0, "wait")


def test_rolling_window_splitting_has_strict_boundaries():
    windows = list(split_windows(candles(20), WalkForwardConfig(6, 3, 2, 2)))
    assert len(windows) == 5
    assert windows[0].slices() == (slice(0, 6), slice(6, 9), slice(9, 11))
    assert windows[1].slices() == (slice(2, 8), slice(8, 11), slice(11, 13))


def test_no_lookahead_and_fresh_portfolio_per_segment():
    seen = []
    class Spy:
        def __call__(self, frame):
            seen.append(tuple(frame.timestamp))
            return Signal(Action.HOLD, 0, "spy")
    WalkForwardEngine(candles(12), BacktestConfig(), WalkForwardConfig(4, 3, 2, 2)).run({"spy": Spy()})
    # Each segment begins at a new length-one prefix; no call contains timestamps outside that segment.
    assert [len(x) for x in seen] == [1, 2, 3, 4, 1, 2, 3, 1, 2, 1, 2, 3, 4, 1, 2, 3, 1, 2]
    assert max(seen[0]) < min(seen[4]) < min(seen[7])


def test_results_are_reproducible_and_aggregate_all_metrics():
    args = (candles(), BacktestConfig(fee_rate=0, spread_rate=0, slippage_rate=0), WalkForwardConfig(8, 4, 4, 4))
    first = WalkForwardEngine(*args).run({"repeatable": alternating})
    second = WalkForwardEngine(*args).run({"repeatable": alternating})
    assert first == second
    summary = first["strategies"][0]
    assert set(summary["aggregated_oos_metrics"]["net_return"]) == {"mean", "median", "standard_deviation", "best_window", "worst_window"}
    assert len(summary["aggregated_oos_metrics"]) == 12


def test_qualification_rules_fail_weak_strategy():
    def idle(window): return Signal(Action.HOLD, 0, "idle")
    result = WalkForwardEngine(candles(), BacktestConfig(), WalkForwardConfig(8, 4, 4, 4),
        QualificationRules(minimum_oos_trades=2)).run({"idle": idle})["strategies"][0]
    assert not result["qualified"] and result["qualification_result"] == "Failed"
    assert "OOS trade count below minimum" in result["failure_reasons"]
    assert "expectancy is not positive" in result["failure_reasons"]


def test_stability_penalizes_one_lucky_window():
    base = {"net_return": -1, "trade_count": 2}
    lucky = [dict(base, net_return=30), base, base]
    consistent = [dict(base, net_return=2), dict(base, net_return=2.1), dict(base, net_return=1.9)]
    assert stability(consistent, 0, 3)[2] > stability(lucky, 0, 3)[2]


def test_report_generation_contains_required_sections(tmp_path):
    result = WalkForwardEngine(candles(), BacktestConfig(fee_rate=0), WalkForwardConfig(8, 4, 4, 4)).run({"a": alternating})
    json_path, csv_path = write_reports(result, tmp_path)
    payload = json.loads((tmp_path / "walkforward_summary.json").read_text())
    assert json_path.endswith("walkforward_summary.json") and csv_path.endswith("walkforward_summary.csv")
    assert payload["windows"][0]["is_metrics"] and payload["windows"][0]["validation_metrics"] and payload["windows"][0]["oos_metrics"]
    csv_text = (tmp_path / "walkforward_summary.csv").read_text()
    assert "qualification_result" in csv_text and "stability_score" in csv_text


def test_metric_aggregation_handles_infinite_profit_factor():
    row = {key: 1.0 for key in ("net_return", "cagr", "win_rate", "profit_factor", "sharpe_ratio",
        "sortino_ratio", "maximum_drawdown", "expectancy", "average_r_multiple",
        "average_trade_duration", "trade_count", "fees_paid")}
    row["profit_factor"] = float("inf")
    assert aggregate([row])["profit_factor"]["mean"] == 5.0
