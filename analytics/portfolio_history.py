"""Portfolio snapshots and equity/return analytics."""
from __future__ import annotations

from datetime import datetime, timezone


def store_snapshot(tid, snapshot: dict, *, async_write: bool = True):
    event_id = tid.deterministic_id("portfolio", snapshot.get("timestamp"))
    tid.enqueue("portfolio", snapshot, event_id=event_id)
    return True


def apply_snapshot(con, snapshot: dict):
    fields = ("timestamp", "cash", "equity", "unrealized_pnl", "realized_pnl", "drawdown",
              "open_positions", "exposure", "portfolio_value")
    values = [snapshot.get(x, 0) for x in fields]
    con.execute(f"INSERT OR IGNORE INTO portfolio_history ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})", values)


def get_equity_curve(tid, *, start=None, end=None, limit=10000):
    clauses, values = [], []
    if start is not None: clauses.append("timestamp>=?"); values.append(start)
    if end is not None: clauses.append("timestamp<=?"); values.append(end)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with tid.connection(readonly=True) as con:
        rows = con.execute(f"SELECT * FROM portfolio_history{where} ORDER BY timestamp LIMIT ?", (*values, min(limit, 100000))).fetchall()
        return [dict(x) for x in rows]


def _period_returns(tid, period: str):
    fmt = {"daily": "%Y-%m-%d", "weekly": "%Y-%W", "monthly": "%Y-%m"}[period]
    curve = get_equity_curve(tid, limit=100000)
    groups = {}
    for row in curve:
        key = datetime.fromtimestamp(row["timestamp"], timezone.utc).strftime(fmt)
        groups.setdefault(key, [row["equity"], row["equity"]])[1] = row["equity"]
    return [{"period": k, "return": ((v[1] / v[0]) - 1) if v[0] else 0} for k, v in groups.items()]


def get_daily_returns(tid): return _period_returns(tid, "daily")
def get_weekly_returns(tid): return _period_returns(tid, "weekly")
def get_monthly_returns(tid): return _period_returns(tid, "monthly")


def get_rolling_returns(tid, window=30, *, limit=10000):
    curve = get_equity_curve(tid, limit=limit)
    window = max(1, int(window))
    return [{"timestamp": row["timestamp"], "return": row["equity"] / curve[i-window]["equity"] - 1}
            for i, row in enumerate(curve) if i >= window and curve[i-window]["equity"]]


def get_rolling_drawdown(tid, window=30, *, limit=10000):
    curve = get_equity_curve(tid, limit=limit)
    window = max(1, int(window))
    result = []
    for i, row in enumerate(curve):
        peak = max(x["equity"] for x in curve[max(0, i-window+1):i+1])
        result.append({"timestamp": row["timestamp"], "drawdown": (peak-row["equity"])/peak if peak else 0})
    return result
