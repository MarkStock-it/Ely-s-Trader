"""Explainable strategy-decision journal."""
import time


def log_decision(tid, *, symbol, strategy, signal=None, confidence=None,
                 indicator_values=None, research_result=None, risk_result=None,
                 final_decision, timestamp=None, async_write=True):
    values = (timestamp or time.time(), symbol, strategy, signal, confidence,
              tid.json_value(indicator_values), tid.json_value(research_result),
              tid.json_value(risk_result), final_decision)
    def write():
        with tid.connection() as con:
            con.execute("""INSERT INTO decision_journal
             (timestamp,symbol,strategy_id,signal,confidence,indicator_values,research_result,risk_result,final_decision)
             VALUES (?,?,?,?,?,?,?,?,?)""", values)
    return tid.submit(write) if async_write else (write() or True)


def get_decision_history(tid, *, strategy=None, symbol=None, limit=100, offset=0):
    clauses, values = [], []
    if strategy: clauses.append("strategy_id=?"); values.append(strategy)
    if symbol: clauses.append("symbol=?"); values.append(symbol)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with tid.connection(readonly=True) as con:
        rows = con.execute(f"SELECT * FROM decision_journal{where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                           (*values, min(limit, 10000), max(offset, 0))).fetchall()
        return [dict(row) for row in rows]
