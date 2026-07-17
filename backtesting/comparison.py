from dataclasses import replace

from .engine import BacktestEngine


def compare_strategies(data, config, strategies, minimum_trades=5):
    rows = []
    for name, fn in strategies.items():
        result = BacktestEngine(data.copy(), replace(config, strategy=name)).run(fn)
        m = result.metrics; trades = m["total_trades"]
        pf = min(m["profit_factor"], 5) if m["profit_factor"] != float("inf") else 5
        activity = min(1.0, trades / max(1, minimum_trades))
        # Risk-adjusted quality, multiplied by activity so tiny samples cannot dominate.
        score = activity * (0.35 * m["total_return"] - 0.30 * m["maximum_drawdown_percentage"] +
                            4 * 0.15 * pf + 4 * 0.15 * m["sharpe_ratio"] + 0.05 * m["win_rate"])
        rows.append({"strategy": name, "net_return": m["total_return"],
                     "max_drawdown": m["maximum_drawdown_percentage"], "profit_factor": m["profit_factor"],
                     "sharpe": m["sharpe_ratio"], "trades": trades, "win_rate": m["win_rate"],
                     "expectancy": m["expectancy"], "fees": m["total_fees"],
                     "composite_score": score, "result": result})
    rows.sort(key=lambda x: x["composite_score"], reverse=True)
    for rank, row in enumerate(rows, 1): row["rank"] = rank
    return rows


def compare_walkforward(data, config, strategies, walkforward_config=None, rules=None, progress=None):
    """Rank strategies by aggregated unseen-window evidence."""
    from walkforward.engine import WalkForwardEngine
    result = WalkForwardEngine(data, config, walkforward_config, rules, progress).run(strategies)
    ranking = []
    for row in result["strategies"]:
        metrics = row["aggregated_oos_metrics"]
        ranking.append({"rank": row["rank"], "strategy": row["strategy"], "status": row["status"],
            "qualified": row["qualified"], "net_return": metrics["net_return"]["mean"],
            "max_drawdown": metrics["maximum_drawdown"]["mean"],
            "win_rate": metrics["win_rate"]["mean"], "profit_factor": metrics["profit_factor"]["mean"],
            "sharpe": metrics["sharpe_ratio"]["mean"], "trades": row["oos_trade_count"],
            "degradation_pct": row["degradation_pct"], "profitable_window_pct": row["profitable_window_pct"],
            "stability_score": row["stability_score"], "composite_score": row["stability_score"]})
    return ranking, result
