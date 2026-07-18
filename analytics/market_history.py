"""Per-candle market context persistence."""
import time


def store_market(tid, *, symbol, timeframe, regime=None, atr=None, volume=None,
                 volatility=None, trend_strength=None, timestamp=None, async_write=True):
    payload = {"timestamp": timestamp or time.time(), "symbol": symbol, "timeframe": timeframe,
               "regime": regime, "atr": atr, "volume": volume, "volatility": volatility,
               "trend_strength": trend_strength}
    event_id = tid.deterministic_id("market", [payload["timestamp"], symbol, timeframe])
    tid.enqueue("market", payload, event_id=event_id)
    return True


def apply_market(con, payload):
    fields = ("timestamp", "symbol", "timeframe", "regime", "atr", "volume", "volatility", "trend_strength")
    con.execute(f"INSERT OR IGNORE INTO market_history ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",
                [payload.get(x) for x in fields])


def get_market_history(tid, *, symbol=None, timeframe=None, limit=1000, offset=0):
    clauses, values = [], []
    if symbol: clauses.append("symbol=?"); values.append(symbol)
    if timeframe: clauses.append("timeframe=?"); values.append(timeframe)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with tid.connection(readonly=True) as con:
        rows = con.execute(f"SELECT * FROM market_history{where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                           (*values, min(limit, 10000), max(offset, 0))).fetchall()
        return [dict(row) for row in rows]
