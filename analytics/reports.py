"""Deterministic CSV/JSON report generation from the TID."""
import csv
import json
from pathlib import Path
from .portfolio_history import get_equity_curve, get_monthly_returns
from .strategy_stats import get_strategy_statistics
from .trade_history import get_trades


def _csv(path, rows):
    rows = list(rows)
    with path.open("w", newline="", encoding="utf-8") as handle:
        if not rows: return
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader(); writer.writerows(rows)


def generate_reports(tid, output_dir="reports"):
    tid.flush()
    root = Path(output_dir); root.mkdir(parents=True, exist_ok=True)
    trades = get_trades(tid, limit=10000)
    portfolio = get_equity_curve(tid, limit=100000)
    stats = get_strategy_statistics(tid)
    monthly = get_monthly_returns(tid)
    _csv(root / "trade_history.csv", trades)
    _csv(root / "equity_curve.csv", ({"timestamp": x["timestamp"], "equity": x["equity"], "drawdown": x["drawdown"]} for x in portfolio))
    _csv(root / "portfolio_history.csv", portfolio)
    (root / "strategy_statistics.json").write_text(json.dumps(stats, indent=2, allow_nan=False, default=str), encoding="utf-8")
    (root / "monthly_summary.json").write_text(json.dumps(monthly, indent=2, allow_nan=False, default=str), encoding="utf-8")
    return {name: str(root / name) for name in ("trade_history.csv", "equity_curve.csv", "strategy_statistics.json", "monthly_summary.json", "portfolio_history.csv")}
