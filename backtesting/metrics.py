import math
from typing import Dict, List

import numpy as np


def calculate_metrics(starting_balance: float, ending_equity: float, trades, equity,
                      first_close: float, last_close: float) -> Dict[str, float]:
    profits = [t.net_profit for t in trades]
    wins, losses = [p for p in profits if p > 0], [p for p in profits if p < 0]
    gross_profit, gross_loss = sum(wins), sum(losses)
    returns = np.array([p / starting_balance for p in profits], dtype=float)
    sharpe = float(np.mean(returns) / np.std(returns) * math.sqrt(len(returns))) if len(returns) > 1 and np.std(returns) > 0 else 0.0
    downside = returns[returns < 0]
    sortino = float(np.mean(returns) / np.std(downside) * math.sqrt(len(returns))) if len(downside) > 1 and np.std(downside) > 0 else 0.0
    max_dd_amount = max((x["drawdown"] for x in equity), default=0.0)
    max_dd_pct = max((x["drawdown_percentage"] for x in equity), default=0.0)
    total_return = (ending_equity / starting_balance - 1) * 100
    exposure = sum(t.holding_duration for t in trades)
    span = max(0.0, _seconds(equity[-1]["timestamp"], equity[0]["timestamp"])) if len(equity) > 1 else 0.0
    return {
        "starting_balance": starting_balance, "ending_equity": ending_equity,
        "net_profit": ending_equity - starting_balance, "total_return": total_return,
        "buy_and_hold_return": (last_close / first_close - 1) * 100,
        "total_trades": len(trades), "winning_trades": len(wins), "losing_trades": len(losses),
        "win_rate": len(wins) / len(trades) * 100 if trades else 0.0,
        "gross_profit": gross_profit, "gross_loss": gross_loss,
        "profit_factor": gross_profit / abs(gross_loss) if gross_loss else (float("inf") if gross_profit else 0.0),
        "average_trade": np.mean(profits).item() if profits else 0.0,
        "average_win": np.mean(wins).item() if wins else 0.0, "average_loss": np.mean(losses).item() if losses else 0.0,
        "expectancy": np.mean(profits).item() if profits else 0.0,
        "largest_win": max(wins, default=0.0), "largest_loss": min(losses, default=0.0),
        "maximum_drawdown_amount": max_dd_amount, "maximum_drawdown_percentage": max_dd_pct,
        "sharpe_ratio": sharpe, "sortino_ratio": sortino,
        "calmar_ratio": total_return / max_dd_pct if max_dd_pct else 0.0,
        "consecutive_wins": _max_streak(profits, True), "consecutive_losses": _max_streak(profits, False),
        "total_fees": sum(t.entry_fee + t.exit_fee for t in trades),
        "exposure_time": exposure / span * 100 if span else 0.0,
        "average_holding_duration": np.mean([t.holding_duration for t in trades]).item() if trades else 0.0,
    }


def _max_streak(values: List[float], winning: bool) -> int:
    best = current = 0
    for value in values:
        current = current + 1 if (value > 0) == winning and value != 0 else 0
        best = max(best, current)
    return best


def _seconds(a, b):
    try:
        return (np.datetime64(a) - np.datetime64(b)) / np.timedelta64(1, "s")
    except Exception:
        try: return float(a) - float(b)
        except Exception: return 0.0
