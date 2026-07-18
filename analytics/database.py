"""Durable SQLite outbox and analytics materialization."""
from __future__ import annotations

import atexit
import hashlib
import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import db
import metrics

logger = logging.getLogger("mega_trading_bot.analytics")

SCHEMA = """
CREATE TABLE IF NOT EXISTS analytics_trades (
 trade_id TEXT PRIMARY KEY, strategy_id TEXT NOT NULL, strategy_version TEXT,
 symbol TEXT NOT NULL, timeframe TEXT, direction TEXT NOT NULL,
 entry_time REAL NOT NULL, exit_time REAL NOT NULL, entry_price REAL NOT NULL,
 exit_price REAL NOT NULL, quantity REAL NOT NULL, stop_loss REAL, take_profit REAL,
 fees REAL NOT NULL DEFAULT 0, spread REAL NOT NULL DEFAULT 0,
 slippage REAL NOT NULL DEFAULT 0, gross_pnl REAL NOT NULL, net_pnl REAL NOT NULL,
 return_pct REAL NOT NULL, r_multiple REAL, hold_duration REAL NOT NULL,
 exit_reason TEXT, confidence REAL, risk_multiplier REAL,
 research_approval_id TEXT, market_regime TEXT, config_fingerprint TEXT NOT NULL,
 created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_at_strategy_exit ON analytics_trades(strategy_id, exit_time DESC);
CREATE INDEX IF NOT EXISTS idx_at_symbol_exit ON analytics_trades(symbol, exit_time DESC);
CREATE INDEX IF NOT EXISTS idx_at_exit ON analytics_trades(exit_time DESC);
CREATE TABLE IF NOT EXISTS portfolio_history (
 id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL NOT NULL UNIQUE,
 cash REAL NOT NULL, equity REAL NOT NULL, unrealized_pnl REAL NOT NULL,
 realized_pnl REAL NOT NULL, drawdown REAL NOT NULL, open_positions INTEGER NOT NULL,
 exposure REAL NOT NULL, portfolio_value REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ph_timestamp ON portfolio_history(timestamp);
CREATE TABLE IF NOT EXISTS decision_journal (
 id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE, timestamp REAL NOT NULL,
 symbol TEXT NOT NULL, strategy_id TEXT NOT NULL, signal TEXT, confidence REAL,
 indicator_values TEXT, research_result TEXT, risk_result TEXT, final_decision TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dj_strategy_time ON decision_journal(strategy_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_dj_symbol_time ON decision_journal(symbol, timestamp DESC);
CREATE TABLE IF NOT EXISTS strategy_statistics (
 strategy_id TEXT PRIMARY KEY, trades INTEGER NOT NULL, wins INTEGER NOT NULL,
 losses INTEGER NOT NULL, win_rate REAL NOT NULL, loss_rate REAL NOT NULL,
 profit_factor REAL, expectancy REAL NOT NULL, average_r REAL,
 average_hold_time REAL NOT NULL, sharpe REAL, sortino REAL, max_drawdown REAL NOT NULL,
 largest_winner REAL, largest_loser REAL, consecutive_wins INTEGER NOT NULL,
 consecutive_losses INTEGER NOT NULL, average_confidence REAL,
 average_risk_multiplier REAL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS market_history (
 id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL NOT NULL, symbol TEXT NOT NULL,
 timeframe TEXT NOT NULL, regime TEXT, atr REAL, volume REAL, volatility REAL,
 trend_strength REAL, UNIQUE(timestamp, symbol, timeframe)
);
CREATE INDEX IF NOT EXISTS idx_mh_symbol_tf_time ON market_history(symbol, timeframe, timestamp DESC);
CREATE TABLE IF NOT EXISTS analytics_outbox (
 event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, payload TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','processing','completed','dead_letter')),
 attempts INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL,
 next_attempt_at REAL NOT NULL, locked_at REAL, locked_by TEXT,
 completed_at REAL, last_error TEXT
);
CREATE INDEX IF NOT EXISTS idx_outbox_ready ON analytics_outbox(state,next_attempt_at,created_at);
CREATE INDEX IF NOT EXISTS idx_outbox_locked ON analytics_outbox(state,locked_at);
"""


class TradingIntelligenceDatabase:
    """Persist events before acknowledgement and materialize them in the background."""

    def __init__(self, db_path: str | Path, *, asynchronous: bool = True,
                 max_attempts: int = 5, base_backoff: float = .1,
                 max_backoff: float = 30.0, lease_seconds: float = 30.0,
                 poll_interval: float = .1, processor=None):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        db.init_db(self.db_path)
        with db.connect(self.db_path) as con:
            con.executescript(SCHEMA)
            columns = {row[1] for row in con.execute("PRAGMA table_info(decision_journal)")}
            if "event_id" not in columns:
                con.execute("ALTER TABLE decision_journal ADD COLUMN event_id TEXT")
                con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_dj_event ON decision_journal(event_id)")
            con.execute("""UPDATE analytics_outbox SET state='pending',locked_at=NULL,locked_by=NULL,
                         next_attempt_at=? WHERE state='processing' AND (locked_at IS NULL OR locked_at<?)""",
                        (time.time(), time.time() - lease_seconds))
        self.asynchronous = asynchronous
        self.max_attempts = max(1, int(max_attempts))
        self.base_backoff, self.max_backoff = max(0, base_backoff), max(0, max_backoff)
        self.lease_seconds, self.poll_interval = lease_seconds, poll_interval
        self.worker_id = f"{uuid.uuid4()}"
        self._processor = processor or self._materialize
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None
        if asynchronous:
            self._thread = threading.Thread(target=self._worker, name="tid-outbox", daemon=True)
            self._thread.start()
            atexit.register(self.close)
        self.update_metrics()

    def connection(self, *, readonly: bool = False):
        return db.connect(self.db_path, readonly=readonly)

    @staticmethod
    def json_value(value: Any) -> str | None:
        return None if value is None else json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)

    @staticmethod
    def deterministic_id(event_type: str, identity: Any) -> str:
        raw = json.dumps([event_type, identity], sort_keys=True, default=str).encode()
        return f"{event_type}:{hashlib.sha256(raw).hexdigest()}"

    def enqueue(self, event_type: str, payload: dict[str, Any], *, event_id: str | None = None) -> str:
        """Durably commit an event before returning its unique identifier."""
        event_id = event_id or str(uuid.uuid4())
        now = time.time()
        with self.connection() as con:
            # FULL ensures the acknowledgement follows an fsync-backed commit.
            con.execute("PRAGMA synchronous=FULL")
            con.execute("""INSERT OR IGNORE INTO analytics_outbox
              (event_id,event_type,payload,state,attempts,created_at,next_attempt_at)
              VALUES (?,?,?,'pending',0,?,?)""",
              (event_id, event_type, self.json_value(payload), now, now))
        self._wake.set()
        self.update_metrics()
        if not self.asynchronous:
            self.process_pending()
        return event_id

    def _claim(self):
        now = time.time()
        with self.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute("""UPDATE analytics_outbox SET state='pending',locked_at=NULL,locked_by=NULL,
                         next_attempt_at=? WHERE state='processing' AND locked_at<?""",
                        (now, now - self.lease_seconds))
            row = con.execute("""SELECT event_id,event_type,payload,attempts FROM analytics_outbox
                 WHERE state='pending' AND next_attempt_at<=? ORDER BY created_at LIMIT 1""", (now,)).fetchone()
            if not row:
                con.commit(); return None
            changed = con.execute("""UPDATE analytics_outbox SET state='processing',locked_at=?,locked_by=?
                       WHERE event_id=? AND state='pending'""", (now, self.worker_id, row["event_id"])).rowcount
            con.commit()
            return dict(row) if changed else None

    def process_pending(self, *, limit: int | None = None) -> int:
        processed = 0
        while limit is None or processed < limit:
            event = self._claim()
            if not event: break
            try:
                # Materialization and completion acknowledgement share one commit.
                with self.connection() as con:
                    self._processor(con, event["event_type"], json.loads(event["payload"]), event["event_id"])
                    changed = con.execute("""UPDATE analytics_outbox SET state='completed',completed_at=?,
                         locked_at=NULL,locked_by=NULL,last_error=NULL WHERE event_id=? AND state='processing' AND locked_by=?""",
                         (time.time(), event["event_id"], self.worker_id)).rowcount
                    if changed != 1: raise RuntimeError("outbox lease lost before completion")
                metrics.ANALYTICS_LAST_SUCCESS.set(time.time())
            except Exception as exc:
                attempts = int(event["attempts"]) + 1
                state = "dead_letter" if attempts >= self.max_attempts else "pending"
                delay = min(self.max_backoff, self.base_backoff * (2 ** max(0, attempts - 1)))
                with self.connection() as con:
                    con.execute("""UPDATE analytics_outbox SET state=?,attempts=?,next_attempt_at=?,
                       locked_at=NULL,locked_by=NULL,last_error=? WHERE event_id=? AND locked_by=?""",
                       (state, attempts, time.time() + delay, str(exc)[:2000], event["event_id"], self.worker_id))
                logger.warning("Analytics event %s failed attempt %s: %s", event["event_id"], attempts, exc)
            processed += 1
            self.update_metrics()
        return processed

    def _materialize(self, con, event_type: str, payload: dict, event_id: str):
        if event_type == "trade":
            from .trade_history import apply_trade
            apply_trade(con, payload)
        elif event_type == "portfolio":
            from .portfolio_history import apply_snapshot
            apply_snapshot(con, payload)
        elif event_type == "decision":
            from .decision_log import apply_decision
            apply_decision(con, payload, event_id)
        elif event_type == "market":
            from .market_history import apply_market
            apply_market(con, payload)
        else:
            raise ValueError(f"Unsupported analytics event type: {event_type}")

    def _worker(self):
        while not self._stop.is_set():
            if not self.process_pending(limit=100):
                self._wake.wait(self.poll_interval); self._wake.clear()

    def status(self):
        now = time.time()
        with self.connection(readonly=True) as con:
            row = con.execute("""SELECT
              SUM(CASE WHEN state IN ('pending','processing') THEN 1 ELSE 0 END) pending,
              SUM(CASE WHEN state='dead_letter' THEN 1 ELSE 0 END) failed,
              MIN(CASE WHEN state IN ('pending','processing') THEN created_at END) oldest,
              MAX(completed_at) last_success FROM analytics_outbox""").fetchone()
        return {"pending_events": int(row["pending"] or 0), "failed_events": int(row["failed"] or 0),
                "oldest_pending_age": max(0, now-row["oldest"]) if row["oldest"] else 0,
                "last_successful_processing_time": row["last_success"]}

    def update_metrics(self):
        status = self.status()
        metrics.ANALYTICS_PENDING.set(status["pending_events"])
        metrics.ANALYTICS_FAILED.set(status["failed_events"])
        metrics.ANALYTICS_OLDEST_PENDING_AGE.set(status["oldest_pending_age"])
        if status["last_successful_processing_time"]:
            metrics.ANALYTICS_LAST_SUCCESS.set(status["last_successful_processing_time"])

    def flush(self, timeout: float = 10.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.process_pending(limit=100)
            if self.status()["pending_events"] == 0: return True
            time.sleep(min(self.poll_interval, .05))
        return False

    def close(self):
        self._stop.set(); self._wake.set()
        if self._thread and self._thread.is_alive(): self._thread.join(timeout=2)
        self.flush()
