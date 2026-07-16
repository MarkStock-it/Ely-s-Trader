"""db.py

Lightweight SQLite persistence for orders, events, and state. Designed to be
safe to use from multiple threads via simple connections per operation.
"""
import os
import sqlite3
import time
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger("mega_trading_bot.db")


def init_db(db_path: str) -> None:
    d = os.path.dirname(db_path)
    if d:
        os.makedirs(d, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                symbol TEXT,
                side TEXT,
                amount REAL,
                entry_price REAL,
                status TEXT,
                state TEXT,
                created_ts REAL,
                updated_ts REAL,
                meta TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                level TEXT,
                msg TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS fills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT,
                ts REAL,
                price REAL,
                amount REAL,
                fee REAL,
                side TEXT,
                meta TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS idempotency (
                client_id TEXT PRIMARY KEY,
                exchange_id TEXT,
                created_ts REAL
            )
            """
        )
        con.commit()
    finally:
        con.close()


def log_order(db_path: str, order: Dict[str, Any]) -> None:
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO orders (id, symbol, side, amount, entry_price, status, state, created_ts, updated_ts, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                order.get("id"),
                order.get("symbol"),
                order.get("side"),
                float(order.get("amount", 0)),
                float(order.get("entry_price", 0)),
                order.get("status", "unknown"),
                order.get("state", order.get("status", "unknown")),
                order.get("created_ts", time.time()),
                time.time(),
                str(order.get("meta", "")),
            ),
        )
        con.commit()
    except Exception:
        logger.exception("Failed to log order")
    finally:
        try:
            con.close()
        except Exception:
            pass


def get_idempotent_mapping(db_path: str, client_id: str) -> Optional[str]:
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute("SELECT exchange_id FROM idempotency WHERE client_id = ?", (client_id,))
        row = cur.fetchone()
        return row[0] if row else None
    except Exception:
        logger.exception("Failed to fetch idempotent mapping")
        return None
    finally:
        try:
            con.close()
        except Exception:
            pass


def save_idempotent_mapping(db_path: str, client_id: str, exchange_id: str) -> None:
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute("INSERT OR REPLACE INTO idempotency (client_id, exchange_id, created_ts) VALUES (?, ?, ?)", (client_id, exchange_id, time.time()))
        con.commit()
    except Exception:
        logger.exception("Failed to save idempotent mapping")
    finally:
        try:
            con.close()
        except Exception:
            pass


def update_order_status(db_path: str, order_id: str, status: str, state: str = None) -> None:
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        if state is None:
            state = status
        cur.execute("UPDATE orders SET status = ?, state = ?, updated_ts = ? WHERE id = ?", (status, state, time.time(), order_id))
        con.commit()
    except Exception:
        logger.exception("Failed to update order status")
    finally:
        try:
            con.close()
        except Exception:
            pass


def log_fill(db_path: str, order_id: str, price: float, amount: float, fee: float = 0.0, side: Optional[str] = None, meta: str = "") -> None:
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute("INSERT INTO fills (order_id, ts, price, amount, fee, side, meta) VALUES (?, ?, ?, ?, ?, ?, ?)", (order_id, time.time(), price, amount, fee, side, meta))
        con.commit()
    except Exception:
        logger.exception("Failed to log fill")
    finally:
        try:
            con.close()
        except Exception:
            pass


def get_open_orders(db_path: str) -> List[Dict[str, Any]]:
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute("SELECT id, symbol, side, amount, entry_price, status, state, created_ts FROM orders WHERE state != 'closed'")
        rows = cur.fetchall()
        return [
            {"id": r[0], "symbol": r[1], "side": r[2], "amount": r[3], "entry_price": r[4], "status": r[5], "state": r[6], "created_ts": r[7]}
            for r in rows
        ]
    except Exception:
        logger.exception("Failed to fetch open orders")
        return []
    finally:
        try:
            con.close()
        except Exception:
            pass


def get_open_orders(db_path: str) -> List[Dict[str, Any]]:
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute("SELECT id, symbol, side, amount, entry_price, status, created_ts FROM orders WHERE status != 'closed'")
        rows = cur.fetchall()
        return [
            {"id": r[0], "symbol": r[1], "side": r[2], "amount": r[3], "entry_price": r[4], "status": r[5], "created_ts": r[6]}
            for r in rows
        ]
    except Exception:
        logger.exception("Failed to fetch open orders")
        return []
    finally:
        try:
            con.close()
        except Exception:
            pass


def save_event(db_path: str, level: str, msg: str) -> None:
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute("INSERT INTO events (ts, level, msg) VALUES (?, ?, ?)", (time.time(), level, msg))
        con.commit()
    except Exception:
        logger.exception("Failed to save event")
    finally:
        try:
            con.close()
        except Exception:
            pass
