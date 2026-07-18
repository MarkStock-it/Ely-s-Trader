import json
import threading
import time

import db
from analytics.database import TradingIntelligenceDatabase
from analytics.decision_log import get_decision_history, log_decision
from analytics.reconciliation import reconcile_missing_trades
from analytics.trade_history import get_trade, get_trades, store_trade


def trade(number=1):
    return {"trade_id": f"trade-{number}", "strategy_id": "macd", "strategy_version": "1",
            "symbol": "BTCUSDT", "timeframe": "1m", "direction": "buy",
            "entry_time": 1000, "exit_time": 1100, "entry_price": 100,
            "exit_price": 110, "quantity": 1, "stop_loss": 95, "take_profit": 115,
            "fees": 1, "spread": .001, "slippage": .002, "gross_pnl": 10,
            "net_pnl": 9, "return_pct": 9, "r_multiple": 1.8, "hold_duration": 100,
            "exit_reason": "target", "confidence": .8, "risk_multiplier": 1,
            "research_approval_id": None, "market_regime": "bull",
            "config_fingerprint": "abc"}


def test_abrupt_restart_recovers_pending_event(tmp_path):
    path = tmp_path / "tid.db"
    failing = TradingIntelligenceDatabase(path, asynchronous=False, base_backoff=60,
        processor=lambda *args: (_ for _ in ()).throw(RuntimeError("crash")))
    store_trade(failing, trade())
    assert failing.status()["pending_events"] == 1 and get_trade(failing, "trade-1") is None
    with failing.connection() as con:
        con.execute("""UPDATE analytics_outbox SET state='processing',next_attempt_at=0,
                    locked_at=0,locked_by='crashed-process'""")
    recovered = TradingIntelligenceDatabase(path, asynchronous=False)
    recovered.process_pending()
    assert get_trade(recovered, "trade-1") is not None


def test_duplicate_delivery_and_idempotent_replay(tmp_path):
    tid = TradingIntelligenceDatabase(tmp_path / "tid.db", asynchronous=False)
    store_trade(tid, trade()); store_trade(tid, trade())
    event_id = tid.deterministic_id("trade", "trade-1")
    with tid.connection() as con:
        con.execute("UPDATE analytics_outbox SET state='pending',next_attempt_at=0,completed_at=NULL WHERE event_id=?", (event_id,))
    tid.process_pending()
    assert len(get_trades(tid)) == 1
    with tid.connection(readonly=True) as con:
        assert con.execute("SELECT state FROM analytics_outbox WHERE event_id=?", (event_id,)).fetchone()[0] == "completed"


def test_failed_transaction_retries_without_partial_commit(tmp_path):
    calls = {"count": 0}; holder = {}
    def processor(con, kind, payload, event_id):
        calls["count"] += 1
        if calls["count"] == 1:
            con.execute("INSERT INTO decision_journal(event_id,timestamp,symbol,strategy_id,final_decision) VALUES (?,?,?,?,?)",
                        (event_id, 1, "BAD", "bad", "partial"))
            raise RuntimeError("transaction failed")
        holder["tid"]._materialize(con, kind, payload, event_id)
    tid = TradingIntelligenceDatabase(tmp_path / "tid.db", asynchronous=False, base_backoff=0, processor=processor)
    holder["tid"] = tid
    log_decision(tid, symbol="BTCUSDT", strategy="macd", final_decision="accepted")
    assert calls["count"] == 2
    assert [x["symbol"] for x in get_decision_history(tid)] == ["BTCUSDT"]


def test_dead_letter_after_bounded_failures(tmp_path):
    tid = TradingIntelligenceDatabase(tmp_path / "tid.db", asynchronous=False, max_attempts=3,
        base_backoff=0, processor=lambda *args: (_ for _ in ()).throw(ValueError("poison")))
    log_decision(tid, symbol="BTCUSDT", strategy="macd", final_decision="test")
    assert tid.status() == {"pending_events": 0, "failed_events": 1,
                            "oldest_pending_age": 0, "last_successful_processing_time": None}
    with tid.connection(readonly=True) as con:
        row = con.execute("SELECT attempts,last_error FROM analytics_outbox").fetchone()
    assert row["attempts"] == 3 and "poison" in row["last_error"]


def test_missing_trade_reconciliation_is_idempotent(tmp_path):
    path = str(tmp_path / "tid.db"); db.init_db(path)
    db.log_order(path, {"id": "sell-1", "symbol": "BTCUSDT", "side": "sell", "amount": 1,
                 "entry_price": 110, "status": "closed", "state": "closed", "created_ts": 1000})
    meta = json.dumps({"entry_value": 100, "entry_fees": .1, "exit_fees": .1,
                       "gross_profit": 10, "net_profit": 9.8, "return_percentage": 9.8,
                       "spread_rate": .001, "slippage_rate": .002})
    db.log_fill(path, "sell-1", 110, 1, .1, "sell", meta)
    tid = TradingIntelligenceDatabase(path, asynchronous=False)
    first = reconcile_missing_trades(tid, {"STRATEGY": "macd", "INTERVAL": "1m"})
    second = reconcile_missing_trades(tid, {"STRATEGY": "macd", "INTERVAL": "1m"})
    assert first["reconciled"] == 1 and second["already_present"] == 1
    assert len(get_trades(tid)) == 1 and get_trades(tid)[0]["exit_reason"] == "execution_reconciliation"


def test_concurrent_workers_claim_event_once(tmp_path):
    path = tmp_path / "tid.db"
    seed = TradingIntelligenceDatabase(path, asynchronous=False, base_backoff=60,
        processor=lambda *args: (_ for _ in ()).throw(RuntimeError("hold")))
    store_trade(seed, trade())
    with seed.connection() as con:
        con.execute("UPDATE analytics_outbox SET next_attempt_at=0,attempts=0")
    one = TradingIntelligenceDatabase(path, asynchronous=False)
    two = TradingIntelligenceDatabase(path, asynchronous=False)
    barrier = threading.Barrier(3)
    results = []
    def run(worker):
        barrier.wait(); results.append(worker.process_pending(limit=1))
    threads = [threading.Thread(target=run, args=(worker,)) for worker in (one, two)]
    for thread in threads: thread.start()
    barrier.wait()
    for thread in threads: thread.join()
    assert sum(results) == 1 and len(get_trades(one)) == 1
