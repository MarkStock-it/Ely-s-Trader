"""Schema, atomic writes and non-blocking ingestion for trading intelligence."""
from __future__ import annotations

import atexit
import json
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any, Callable

import db

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
 id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL NOT NULL, symbol TEXT NOT NULL,
 strategy_id TEXT NOT NULL, signal TEXT, confidence REAL, indicator_values TEXT,
 research_result TEXT, risk_result TEXT, final_decision TEXT NOT NULL
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
"""


class TradingIntelligenceDatabase:
    """Facade over the existing SQLite database with optional async writes."""

    def __init__(self, db_path: str | Path, *, asynchronous: bool = True, queue_size: int = 10000):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        db.init_db(self.db_path)
        with db.connect(self.db_path) as con:
            con.executescript(SCHEMA)
        self.asynchronous = asynchronous
        self._queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._stop = threading.Event()
        self._thread = None
        if asynchronous:
            self._thread = threading.Thread(target=self._worker, name="tid-writer", daemon=True)
            self._thread.start()
            atexit.register(self.close)

    def connection(self, *, readonly: bool = False):
        return db.connect(self.db_path, readonly=readonly)

    def submit(self, operation: Callable, *args, **kwargs) -> bool:
        if not self.asynchronous:
            operation(*args, **kwargs)
            return True
        try:
            self._queue.put_nowait((operation, args, kwargs))
            return True
        except queue.Full:
            logger.error("TID writer queue full; writing synchronously to preserve history")
            operation(*args, **kwargs)
            return False

    def _worker(self):
        while not self._stop.is_set() or not self._queue.empty():
            try:
                operation, args, kwargs = self._queue.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                operation(*args, **kwargs)
            except Exception:
                logger.exception("TID background write failed")
            finally:
                self._queue.task_done()

    def flush(self):
        if self.asynchronous:
            self._queue.join()

    def close(self):
        if self._thread and self._thread.is_alive():
            self._stop.set()
            self.flush()
            self._thread.join(timeout=2)

    @staticmethod
    def json_value(value: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
