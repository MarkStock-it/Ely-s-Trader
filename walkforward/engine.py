from dataclasses import replace

from backtesting.data_loader import validate_ohlcv
from backtesting.engine import BacktestEngine
from .metrics import aggregate, degradation, stability, window_metrics
from .models import QualificationRules, WalkForwardConfig
from .splitter import split_windows


class WalkForwardEngine:
    def __init__(self, data, backtest_config, config=None, rules=None, progress=None):
        self.data = validate_ohlcv(data)
        self.backtest_config = backtest_config
        self.config = config or WalkForwardConfig()
        self.rules = rules or QualificationRules()
        self.progress = progress

    def run(self, strategies):
        windows = list(split_windows(self.data, self.config))
        if not windows:
            needed = self.config.train_size + self.config.validation_size + self.config.test_size
            raise ValueError(f"Not enough candles for one walk-forward window (need {needed})")
        rows = []
        total = len(windows) * len(strategies)
        completed = 0
        for strategy_id, strategy in strategies.items():
            window_rows = []
            for window in windows:
                segments = []
                for label, part in zip(("is_metrics", "validation_metrics", "oos_metrics"), window.slices()):
                    # Independent data and engine instances enforce both portfolio reset and temporal isolation.
                    result = BacktestEngine(self.data.iloc[part].reset_index(drop=True).copy(),
                                            replace(self.backtest_config, strategy=strategy_id)).run(strategy)
                    segments.append(window_metrics(result))
                train, validation, oos = segments
                window_rows.append({"strategy": strategy_id, "window": window.number,
                    "train_start": str(self.data.timestamp.iloc[window.train_start]),
                    "train_end": str(self.data.timestamp.iloc[window.train_end - 1]),
                    "validation_start": str(self.data.timestamp.iloc[window.validation_start]),
                    "validation_end": str(self.data.timestamp.iloc[window.validation_end - 1]),
                    "oos_start": str(self.data.timestamp.iloc[window.test_start]),
                    "oos_end": str(self.data.timestamp.iloc[window.test_end - 1]),
                    "is_metrics": train, "validation_metrics": validation, "oos_metrics": oos})
                completed += 1
                if self.progress: self.progress(completed, total, strategy_id, window.number)
            rows.append(self._summarize(strategy_id, window_rows))
        rows.sort(key=lambda x: (x["qualified"], x["stability_score"]), reverse=True)
        for rank, row in enumerate(rows, 1): row["rank"] = rank
        return {"configuration": vars(self.config), "qualification_rules": vars(self.rules),
                "strategies": rows, "windows": [w for row in rows for w in row["windows"]]}

    def _summarize(self, strategy_id, windows):
        is_rows = [x["is_metrics"] for x in windows]; oos_rows = [x["oos_metrics"] for x in windows]
        deg = degradation(is_rows, oos_rows)
        profitable, consistency, stability_score = stability(oos_rows, deg, self.rules.minimum_oos_trades)
        agg = aggregate(oos_rows); total_trades = sum(x["trade_count"] for x in oos_rows)
        failures = []
        if total_trades < self.rules.minimum_oos_trades: failures.append("OOS trade count below minimum")
        if agg["profit_factor"]["mean"] < self.rules.minimum_profit_factor: failures.append("profit factor below threshold")
        if max(x["maximum_drawdown"] for x in oos_rows) > self.rules.maximum_drawdown_pct: failures.append("drawdown exceeds limit")
        if agg["expectancy"]["mean"] <= 0: failures.append("expectancy is not positive")
        if 100 - profitable > self.rules.maximum_losing_window_pct: failures.append("too many losing windows")
        if deg > self.rules.maximum_degradation_pct: failures.append("excessive IS-to-OOS degradation")
        qualified = not failures
        status = "Qualified" if qualified and stability_score >= 60 else "Stable" if qualified else "Needs Review" if stability_score >= 40 else "Rejected"
        return {"strategy": strategy_id, "qualified": qualified, "status": status,
                "qualification_result": "Approved" if qualified else "Failed", "failure_reasons": failures,
                "degradation_pct": deg, "profitable_window_pct": profitable,
                "consistency_score": consistency, "stability_score": stability_score,
                "oos_trade_count": total_trades, "aggregated_oos_metrics": agg, "windows": windows}
