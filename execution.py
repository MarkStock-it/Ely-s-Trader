"""execution.py

ExecutionEngine: idempotent order submission, state machine, retries, and DB recording.
"""
import time
import logging
import threading
from typing import Dict, Any, Optional

import db
import metrics

logger = logging.getLogger("mega_trading_bot.execution")
PROM_AVAILABLE = getattr(metrics, "PROM_AVAILABLE", False)


class ExecutionEngine:
    def __init__(self, ex_mgr, db_path: str, cfg: Dict[str, Any], circuit_breaker=None):
        self.ex_mgr = ex_mgr
        self.db_path = db_path
        self.cfg = cfg
        self.cb = circuit_breaker

    def create_order(self, symbol: str, side: str, amount: float, price: Optional[float] = None, order_type: str = "market", client_oid: Optional[str] = None) -> Dict[str, Any]:
        """Create order with idempotency and basic state management.

        Returns order dict with at least `id` and `status`.
        """
        # pre-flight: circuit breaker
        if not self.cfg.get("PAPER_MODE") and self.cb is not None and not self.cb.allow():
            raise RuntimeError("Circuit breaker prevents new orders")

        # round amount/price according to exchange rules
        try:
            amount = self.ex_mgr.round_amount(symbol, amount)
            if price is not None:
                price = self.ex_mgr.round_price(symbol, price)
        except Exception:
            logger.debug("Rounding failed; proceeding with raw amount/price")

        # preflight validate size & notional
        try:
            ok, msg = self.ex_mgr.preflight_validate(symbol, amount, price)
            if not ok:
                raise ValueError(f"Preflight validation failed: {msg}")
        except Exception as e:
            logger.exception("Preflight validation error: %s", e)
            raise

        # idempotency: check existing client_oid mapping
        oid = client_oid or f"cli_{int(time.time()*1000)}"
        try:
            existing = db.get_idempotent_mapping(self.db_path, oid)
            if existing:
                # fetch existing order status
                return {"id": existing, "status": "known_from_idempotency"}
        except Exception:
            logger.debug("Idempotency check failed; continuing")

        # record NEW order in DB
        order = {"id": oid, "symbol": symbol, "side": side, "amount": amount, "entry_price": price or 0.0, "status": "new", "state": "new", "created_ts": time.time(), "meta": ""}
        try:
            db.log_order(self.db_path, order)
        except Exception:
            logger.debug("Failed to persist new order record")

        # paper mode: simulate immediate fill
        if self.cfg.get("PAPER_MODE") or not (self.cfg.get("API_KEY") and self.cfg.get("API_SECRET")):
            # mark filled
            try:
                db.log_fill(self.db_path, oid, price or 0.0, amount, 0.0, side, "paper")
                db.update_order_status(self.db_path, oid, "closed", "closed")
            except Exception:
                logger.debug("Failed to persist paper fill")
            return {"id": oid, "status": "closed", "filled": amount}

        # live mode: attempt to place via exchange
        tries = int(self.cfg.get("ORDER_MAX_TRIES", 3))
        delay = float(self.cfg.get("ORDER_RETRY_DELAY", 0.5))
        last_exc = None
        for attempt in range(1, tries + 1):
            try:
                if PROM_AVAILABLE:
                    metrics.ORDER_ATTEMPTS.inc()
                res = self.ex_mgr.create_market_order(symbol, side, amount) if order_type == "market" else self.ex_mgr.exchange.create_order(symbol, order_type, side, amount, price)
                # log order as sent
                db.update_order_status(self.db_path, oid, "sent", "sent")
                # if exchange returned id, record mapping
                eid = res.get("id") if isinstance(res, dict) else None
                if eid:
                    db.log_order(self.db_path, {"id": eid, "symbol": symbol, "side": side, "amount": amount, "entry_price": price or 0.0, "status": res.get("status", "sent"), "state": res.get("status", "sent"), "created_ts": time.time(), "meta": str(res)})
                    try:
                        db.save_idempotent_mapping(self.db_path, oid, str(eid))
                    except Exception:
                        logger.debug("Failed to save idempotent mapping")
                # simple handling: if order closed on create, mark closed
                status = res.get("status", "closed") if isinstance(res, dict) else "unknown"
                if status == "closed":
                    db.log_fill(self.db_path, eid or oid, price or 0.0, amount, 0.0, side, str(res))
                    db.update_order_status(self.db_path, eid or oid, "closed", "closed")
                    if PROM_AVAILABLE:
                        metrics.FILLS.inc()
                # success
                if self.cb is not None:
                    try:
                        self.cb.record_success()
                    except Exception:
                        pass
                return {"id": eid or oid, "status": status, "raw": res}
            except Exception as e:
                last_exc = e
                logger.exception("Order attempt %s failed", attempt)
                if PROM_AVAILABLE:
                    metrics.ORDER_FAILURES.inc()
                if self.cb is not None:
                    try:
                        self.cb.record_failure()
                    except Exception:
                        pass
                time.sleep(delay * (2 ** (attempt - 1)))

        raise last_exc
