"""execution.py

ExecutionEngine: idempotent order submission, state machine, retries, and DB recording.
"""
import time
import logging
import threading
import json
from decimal import Decimal, InvalidOperation
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
        self._paper_lock = threading.Lock()
        self.paper_cash = Decimal(str(cfg.get("PAPER_START_BALANCE", 10000)))
        self.paper_holdings: Dict[str, Decimal] = {}
        self.paper_cost_basis: Dict[str, Decimal] = {}
        self.paper_gross_basis: Dict[str, Decimal] = {}
        self.paper_entry_fee_basis: Dict[str, Decimal] = {}
        self.paper_fees = Decimal("0")
        self.paper_realized_pnl = Decimal("0")

    @staticmethod
    def _positive_decimal(value, name: str) -> Decimal:
        try:
            result = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a positive number") from exc
        if not result.is_finite() or result <= 0:
            raise ValueError(f"{name} must be greater than zero")
        return result

    def _paper_fill(self, oid: str, symbol: str, side: str, amount: float, market_price: float) -> Dict[str, Any]:
        quantity = self._positive_decimal(amount, "quantity")
        market = self._positive_decimal(market_price, "price")
        side = side.lower()
        if side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        fee_rate = Decimal(str(self.cfg.get("PAPER_FEE_RATE", 0.001)))
        slippage = Decimal(str(self.cfg.get("PAPER_SLIPPAGE_RATE", 0.0005)))
        spread = Decimal(str(self.cfg.get("PAPER_SPREAD_RATE", 0.0002)))
        latency = int(self.cfg.get("PAPER_ORDER_LATENCY_MS", 0))
        if latency < 0:
            raise ValueError("PAPER_ORDER_LATENCY_MS must be non-negative")
        if latency:
            time.sleep(latency / 1000.0)
        if side == "buy":
            fill = market * (Decimal("1") + spread / 2) * (Decimal("1") + slippage)
        else:
            fill = market * (Decimal("1") - spread / 2) * (Decimal("1") - slippage)
        gross = fill * quantity
        fee = gross * fee_rate
        now = time.time()
        with self._paper_lock:
            held = self.paper_holdings.get(symbol, Decimal("0"))
            basis = self.paper_cost_basis.get(symbol, Decimal("0"))
            gross_basis = self.paper_gross_basis.get(symbol, Decimal("0"))
            entry_fee_basis = self.paper_entry_fee_basis.get(symbol, Decimal("0"))
            if side == "buy":
                total = gross + fee
                if total > self.paper_cash:
                    raise ValueError("Insufficient paper cash for purchase including fees")
                self.paper_cash -= total
                self.paper_holdings[symbol] = held + quantity
                self.paper_cost_basis[symbol] = basis + total
                self.paper_gross_basis[symbol] = gross_basis + gross
                self.paper_entry_fee_basis[symbol] = entry_fee_basis + fee
                realized = Decimal("0")
                entry_value = gross
                entry_fees = fee
                gross_profit = Decimal("0")
            else:
                if quantity > held:
                    raise ValueError("Insufficient paper holdings for sale")
                allocated_basis = basis * quantity / held
                entry_value = gross_basis * quantity / held
                entry_fees = entry_fee_basis * quantity / held
                net = gross - fee
                realized = net - allocated_basis
                gross_profit = gross - entry_value
                self.paper_cash += net
                self.paper_holdings[symbol] = held - quantity
                self.paper_cost_basis[symbol] = basis - allocated_basis
                self.paper_gross_basis[symbol] = gross_basis - entry_value
                self.paper_entry_fee_basis[symbol] = entry_fee_basis - entry_fees
                self.paper_realized_pnl += realized
            self.paper_fees += fee
        details = {
            "market_price": float(market), "fill_price": float(fill), "fee": float(fee),
            "slippage_rate": float(slippage), "spread_rate": float(spread), "side": side,
            "quantity": float(quantity), "timestamp": now, "gross_value": float(gross),
            "realized_pnl": float(realized), "paper_cash": float(self.paper_cash),
            "entry_value": float(entry_value), "exit_value": float(gross if side == "sell" else 0),
            "entry_fees": float(entry_fees), "exit_fees": float(fee if side == "sell" else 0),
            "gross_profit": float(gross_profit), "net_profit": float(realized),
            "return_percentage": float(realized / (entry_value + entry_fees) * 100) if side == "sell" else 0.0,
        }
        db.log_fill(self.db_path, oid, float(fill), float(quantity), float(fee), side, json.dumps(details, sort_keys=True))
        db.update_order_status(self.db_path, oid, "closed", "closed")
        db.save_idempotent_mapping(self.db_path, oid, oid)
        return {"id": oid, "status": "closed", "filled": float(quantity), **details}

    def paper_account(self, prices: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        prices = prices or {}
        market_value = sum(qty * Decimal(str(prices.get(symbol, 0))) for symbol, qty in self.paper_holdings.items())
        equity = self.paper_cash + market_value
        return {"cash": float(self.paper_cash), "holdings": {k: float(v) for k, v in self.paper_holdings.items()},
                "average_entry_prices": {k: float(self.paper_gross_basis[k] / v) for k, v in self.paper_holdings.items() if v},
                "fees_paid": float(self.paper_fees), "realized_pnl": float(self.paper_realized_pnl),
                "market_value": float(market_value), "net_equity": float(equity)}

    def create_order(self, symbol: str, side: str, amount: float, price: Optional[float] = None, order_type: str = "market", client_oid: Optional[str] = None) -> Dict[str, Any]:
        """Create order with idempotency and basic state management.

        Returns order dict with at least `id` and `status`.
        """
        import safety
        safety.validate_config(self.cfg)
        self._positive_decimal(amount, "quantity")
        if price is not None:
            self._positive_decimal(price, "price")
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
        self._positive_decimal(amount, "quantity")

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
        if self.cfg.get("PAPER_MODE"):
            if order_type != "market":
                raise ValueError("Paper execution currently supports market orders only")
            if price is None:
                raise ValueError("Paper market orders require a market price")
            return self._paper_fill(oid, symbol, side, amount, price)

        if not self.cfg.get("LIVE_MODE") or not (self.cfg.get("API_KEY") and self.cfg.get("API_SECRET")):
            raise RuntimeError("Live execution blocked: explicit live mode and credentials are required")

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
