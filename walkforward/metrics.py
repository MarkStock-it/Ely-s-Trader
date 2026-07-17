import math
from statistics import mean, median, pstdev

import pandas as pd


METRIC_KEYS = ("net_return", "cagr", "win_rate", "profit_factor", "sharpe_ratio",
               "sortino_ratio", "maximum_drawdown", "expectancy", "average_r_multiple",
               "average_trade_duration", "trade_count", "fees_paid")


def window_metrics(result):
    m = result.metrics
    span_years = _years(result.metadata.get("data_start"), result.metadata.get("data_end"))
    total_return = float(m["total_return"])
    cagr = ((1 + total_return / 100) ** (1 / span_years) - 1) * 100 if span_years > 0 and total_return > -100 else 0.0
    losses = [abs(t.net_profit) for t in result.trades if t.net_profit < 0]
    risk_unit = mean(losses) if losses else result.config.starting_balance * max(result.config.stop_loss_pct or 1.0, 1e-12)
    return {"net_return": total_return, "cagr": cagr, "win_rate": float(m["win_rate"]),
            "profit_factor": float(m["profit_factor"]), "sharpe_ratio": float(m["sharpe_ratio"]),
            "sortino_ratio": float(m["sortino_ratio"]),
            "maximum_drawdown": float(m["maximum_drawdown_percentage"]),
            "expectancy": float(m["expectancy"]),
            "average_r_multiple": mean([t.net_profit / risk_unit for t in result.trades]) if result.trades else 0.0,
            "average_trade_duration": float(m["average_holding_duration"]),
            "trade_count": int(m["total_trades"]), "fees_paid": float(m["total_fees"])}


def aggregate(windows):
    result = {}
    for key in METRIC_KEYS:
        values = [float(row[key]) for row in windows]
        # A no-loss profit factor is useful but must not dominate rankings or JSON.
        values = [5.0 if key == "profit_factor" and v == float("inf") else v for v in values]
        values = [v for v in values if math.isfinite(v)] or [0.0]
        result[key] = {"mean": mean(values), "median": median(values),
                       "standard_deviation": pstdev(values),
                       "best_window": max(range(len(values)), key=values.__getitem__) + 1,
                       "worst_window": min(range(len(values)), key=values.__getitem__) + 1}
    return result


def degradation(is_windows, oos_windows):
    is_return = mean([x["net_return"] for x in is_windows])
    oos_return = mean([x["net_return"] for x in oos_windows])
    if is_return <= 0:
        return 0.0 if oos_return >= is_return else 100.0
    return max(0.0, (is_return - oos_return) / abs(is_return) * 100)


def stability(oos_windows, degradation_pct, minimum_trades):
    profitable_pct = mean([x["net_return"] > 0 for x in oos_windows]) * 100
    returns = [x["net_return"] for x in oos_windows]
    dispersion = pstdev(returns) / (abs(mean(returns)) + 1.0)
    consistency = max(0.0, 100.0 / (1.0 + dispersion))
    sample = min(1.0, sum(x["trade_count"] for x in oos_windows) / max(1, minimum_trades))
    window_evidence = min(1.0, len(oos_windows) / 3.0)
    score = sample * window_evidence * (0.45 * profitable_pct + 0.35 * consistency +
                                        0.20 * max(0.0, 100.0 - degradation_pct))
    return profitable_pct, consistency, score


def _years(start, end):
    try: return max(0.0, (pd.Timestamp(end) - pd.Timestamp(start)).total_seconds() / (365.25 * 86400))
    except Exception: return 0.0
