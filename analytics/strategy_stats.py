"""Automatically refreshed lifetime strategy statistics."""
from __future__ import annotations
import math
import time


def _streak(values, winning):
    best = current = 0
    for value in values:
        if value != 0 and (value > 0) == winning:
            current += 1; best = max(best, current)
        else: current = 0
    return best


def update_strategy_statistics(tid, strategy_id: str, *, connection=None):
    def calculate(con):
        rows = con.execute("SELECT net_pnl,r_multiple,hold_duration,confidence,risk_multiplier FROM analytics_trades WHERE strategy_id=? ORDER BY exit_time", (strategy_id,)).fetchall()
        pnl = [float(x["net_pnl"]) for x in rows]
        if not pnl: return
        wins, losses = [x for x in pnl if x > 0], [x for x in pnl if x < 0]
        mean = sum(pnl) / len(pnl)
        variance = sum((x - mean) ** 2 for x in pnl) / len(pnl)
        downside = [min(x, 0) for x in pnl]
        down_dev = math.sqrt(sum(x*x for x in downside) / len(downside)) if downside else 0
        curve = peak = drawdown = 0.0
        for value in pnl:
            curve += value; peak = max(peak, curve); drawdown = max(drawdown, peak - curve)
        def avg(field):
            values = [float(x[field]) for x in rows if x[field] is not None]
            return sum(values) / len(values) if values else None
        record = (strategy_id, len(pnl), len(wins), len(losses), len(wins)/len(pnl), len(losses)/len(pnl),
                  sum(wins)/abs(sum(losses)) if losses else None, mean, avg("r_multiple"),
                  avg("hold_duration") or 0, mean/math.sqrt(variance) if variance else None,
                  mean/down_dev if down_dev else None, drawdown, max(pnl), min(pnl),
                  _streak(pnl, True), _streak(pnl, False), avg("confidence"),
                  avg("risk_multiplier"), time.time())
        con.execute("INSERT OR REPLACE INTO strategy_statistics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", record)
    if connection is not None:
        calculate(connection)
    else:
        with tid.connection() as con:
            calculate(con)


def get_strategy_statistics(tid, strategy=None):
    with tid.connection(readonly=True) as con:
        if strategy:
            row = con.execute("SELECT * FROM strategy_statistics WHERE strategy_id=?", (strategy,)).fetchone()
            return dict(row) if row else None
        return [dict(x) for x in con.execute("SELECT * FROM strategy_statistics ORDER BY expectancy DESC")]


def get_strategy_contribution(tid):
    with tid.connection(readonly=True) as con:
        return [dict(x) for x in con.execute("SELECT strategy_id,COUNT(*) trades,SUM(net_pnl) net_pnl FROM analytics_trades GROUP BY strategy_id ORDER BY net_pnl DESC")]
