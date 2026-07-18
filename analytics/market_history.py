"""Per-candle market context persistence."""
import time


def store_market(tid, *, symbol, timeframe, regime=None, atr=None, volume=None,
                 volatility=None, trend_strength=None, timestamp=None, async_write=True):
    values = (timestamp or time.time(), symbol, timeframe, regime, atr, volume, volatility, trend_strength)
    def write():
        with tid.connection() as con:
            con.execute("""INSERT OR IGNORE INTO market_history
             (timestamp,symbol,timeframe,regime,atr,volume,volatility,trend_strength)
             VALUES (?,?,?,?,?,?,?,?)""", values)
    return tid.submit(write) if async_write else (write() or True)


def get_market_history(tid, *, symbol=None, timeframe=None, limit=1000, offset=0):
    clauses, values = [], []
    if symbol: clauses.append("symbol=?"); values.append(symbol)
    if timeframe: clauses.append("timeframe=?"); values.append(timeframe)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with tid.connection(readonly=True) as con:
        rows = con.execute(f"SELECT * FROM market_history{where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                           (*values, min(limit, 10000), max(offset, 0))).fetchall()
        return [dict(row) for row in rows]
