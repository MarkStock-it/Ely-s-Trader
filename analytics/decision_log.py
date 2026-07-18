"""Explainable strategy-decision journal."""
import time


def log_decision(tid, *, symbol, strategy, signal=None, confidence=None,
                 indicator_values=None, research_result=None, risk_result=None,
                 final_decision, timestamp=None, async_write=True):
    payload = {"timestamp": timestamp or time.time(), "symbol": symbol, "strategy_id": strategy,
               "signal": signal, "confidence": confidence, "indicator_values": indicator_values,
               "research_result": research_result, "risk_result": risk_result,
               "final_decision": final_decision}
    tid.enqueue("decision", payload)
    return True


def apply_decision(con, payload, event_id):
    values = (event_id, payload["timestamp"], payload["symbol"], payload["strategy_id"],
              payload.get("signal"), payload.get("confidence"),
              json_value(payload.get("indicator_values")), json_value(payload.get("research_result")),
              json_value(payload.get("risk_result")), payload["final_decision"])
    con.execute("""INSERT OR IGNORE INTO decision_journal
      (event_id,timestamp,symbol,strategy_id,signal,confidence,indicator_values,research_result,risk_result,final_decision)
      VALUES (?,?,?,?,?,?,?,?,?,?)""", values)


def json_value(value):
    import json
    return None if value is None else json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def get_decision_history(tid, *, strategy=None, symbol=None, limit=100, offset=0):
    clauses, values = [], []
    if strategy: clauses.append("strategy_id=?"); values.append(strategy)
    if symbol: clauses.append("symbol=?"); values.append(symbol)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with tid.connection(readonly=True) as con:
        rows = con.execute(f"SELECT * FROM decision_journal{where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                           (*values, min(limit, 10000), max(offset, 0))).fetchall()
        return [dict(row) for row in rows]
