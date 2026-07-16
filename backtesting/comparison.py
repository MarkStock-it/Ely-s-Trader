from dataclasses import replace

from .engine import BacktestEngine


def compare_strategies(data, config, strategies, minimum_trades=5):
    rows = []
    for name, fn in strategies.items():
        result = BacktestEngine(data.copy(), replace(config, strategy=name)).run(fn)
        m = result.metrics; trades = m["total_trades"]
        pf = min(m["profit_factor"], 5) if m["profit_factor"] != float("inf") else 5
        consistency = m["winning_trades"] / trades if trades else 0
        activity = min(1.0, trades / max(1, minimum_trades))
        score = activity * (0.30 * m["total_return"] - 0.25 * m["maximum_drawdown_percentage"] +
                            5 * 0.20 * pf + 5 * 0.15 * m["sharpe_ratio"] + 10 * 0.10 * consistency)
        rows.append({"strategy": name, "net_return": m["total_return"],
                     "max_drawdown": m["maximum_drawdown_percentage"], "profit_factor": m["profit_factor"],
                     "sharpe": m["sharpe_ratio"], "trades": trades, "win_rate": m["win_rate"],
                     "composite_score": score, "result": result})
    rows.sort(key=lambda x: x["composite_score"], reverse=True)
    for rank, row in enumerate(rows, 1): row["rank"] = rank
    return rows
