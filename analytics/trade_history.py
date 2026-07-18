"""Permanent completed-trade persistence and indexed queries."""
from __future__ import annotations

import time
from typing import Any

FIELDS = ("trade_id", "strategy_id", "strategy_version", "symbol", "timeframe", "direction",
          "entry_time", "exit_time", "entry_price", "exit_price", "quantity", "stop_loss",
          "take_profit", "fees", "spread", "slippage", "gross_pnl", "net_pnl", "return_pct",
          "r_multiple", "hold_duration", "exit_reason", "confidence", "risk_multiplier",
          "research_approval_id", "market_regime", "config_fingerprint")


def store_trade(tid, trade: dict[str, Any], *, async_write: bool = True) -> bool:
    missing = [x for x in ("trade_id", "strategy_id", "symbol", "direction", "entry_time",
                            "exit_time", "entry_price", "exit_price", "quantity",
                            "gross_pnl", "net_pnl", "return_pct", "config_fingerprint") if trade.get(x) is None]
    if missing:
        raise ValueError(f"Missing trade fields: {', '.join(missing)}")
    event_id = tid.deterministic_id("trade", trade["trade_id"])
    tid.enqueue("trade", trade, event_id=event_id)
    return True


def apply_trade(con, trade: dict[str, Any]):
    values = [trade.get(field) for field in FIELDS]
    sql = f"INSERT OR IGNORE INTO analytics_trades ({','.join(FIELDS)},created_at) VALUES ({','.join('?' for _ in FIELDS)},?)"
    con.execute(sql, (*values, time.time()))
    from .strategy_stats import update_strategy_statistics
    update_strategy_statistics(None, str(trade["strategy_id"]), connection=con)


def get_trade(tid, trade_id: str):
    with tid.connection(readonly=True) as con:
        row = con.execute("SELECT * FROM analytics_trades WHERE trade_id=?", (trade_id,)).fetchone()
        return dict(row) if row else None


def get_trades(tid, strategy: str | None = None, symbol: str | None = None,
               *, limit: int = 100, offset: int = 0):
    clauses, values = [], []
    if strategy: clauses.append("strategy_id=?"); values.append(strategy)
    if symbol: clauses.append("symbol=?"); values.append(symbol)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with tid.connection(readonly=True) as con:
        rows = con.execute(f"SELECT * FROM analytics_trades{where} ORDER BY exit_time DESC LIMIT ? OFFSET ?",
                           (*values, min(max(limit, 1), 10000), max(offset, 0))).fetchall()
        return [dict(row) for row in rows]


def _one(tid, order: str):
    with tid.connection(readonly=True) as con:
        row = con.execute(f"SELECT * FROM analytics_trades ORDER BY {order} LIMIT 1").fetchone()
        return dict(row) if row else None


def get_last_trade(tid): return _one(tid, "exit_time DESC")
def get_best_trade(tid): return _one(tid, "net_pnl DESC")
def get_worst_trade(tid): return _one(tid, "net_pnl ASC")


def get_trade_analytics(tid, strategy=None):
    where, values = (" WHERE strategy_id=?", (strategy,)) if strategy else ("", ())
    with tid.connection(readonly=True) as con:
        row = con.execute(f"""SELECT COUNT(*) trades,AVG(hold_duration) average_holding_period,
          AVG(fees) average_fees,AVG(slippage) average_slippage,AVG(spread) average_spread,
          SUM(net_pnl) portfolio_contribution FROM analytics_trades{where}""", values).fetchone()
        return dict(row)
