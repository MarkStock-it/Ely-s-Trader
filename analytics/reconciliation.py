"""Backfill completed execution records missing from analytics_trades."""
from __future__ import annotations

import hashlib
import json

from .trade_history import store_trade


def _fingerprint(cfg):
    safe = {k: v for k, v in cfg.items() if k not in {"API_KEY", "API_SECRET", "TELEGRAM_BOT_TOKEN"}}
    return hashlib.sha256(json.dumps(safe, sort_keys=True, default=str).encode()).hexdigest()


def reconcile_missing_trades(tid, cfg: dict) -> dict:
    """Queue reconstructable sell fills once, without duplicating enriched trades."""
    queued = skipped = already_present = 0
    with tid.connection(readonly=True) as con:
        rows = con.execute("""SELECT f.id fill_id,f.order_id,f.ts,f.price,f.amount,f.fee,f.meta,
          o.symbol,o.created_ts FROM fills f JOIN orders o ON o.id=f.order_id
          WHERE lower(COALESCE(f.side,''))='sell' AND (o.status='closed' OR o.state='closed')
          ORDER BY f.ts""").fetchall()
        for row in rows:
            trade_id = f"reconciled-fill-{row['fill_id']}"
            exists = con.execute("SELECT 1 FROM analytics_trades WHERE trade_id=?", (trade_id,)).fetchone()
            if exists:
                already_present += 1; continue
            try:
                meta = json.loads(row["meta"] or "{}")
            except (TypeError, json.JSONDecodeError):
                skipped += 1; continue
            qty = float(row["amount"] or 0)
            entry_value = float(meta.get("entry_value") or 0)
            if qty <= 0 or entry_value <= 0:
                skipped += 1; continue
            # An enriched TradeManager close may use the entry order ID. Match its
            # immutable execution signature before creating a reconciled fallback.
            duplicate = con.execute("""SELECT 1 FROM analytics_trades WHERE symbol=? AND
                abs(exit_time-?)<2 AND abs(exit_price-?)<0.00000001 AND abs(quantity-?)<0.00000001""",
                (row["symbol"], row["ts"], row["price"], qty)).fetchone()
            if duplicate:
                already_present += 1; continue
            entry_price = entry_value / qty
            entry = con.execute("""SELECT f.ts FROM fills f JOIN orders o ON o.id=f.order_id
                 WHERE o.symbol=? AND lower(COALESCE(f.side,''))='buy' AND f.ts<=?
                 ORDER BY f.ts DESC LIMIT 1""", (row["symbol"], row["ts"])).fetchone()
            entry_time = float(entry["ts"] if entry else row["created_ts"] or row["ts"])
            net = float(meta.get("net_profit", meta.get("realized_pnl", 0)))
            gross = float(meta.get("gross_profit", net))
            fees = float(meta.get("entry_fees", 0)) + float(meta.get("exit_fees", row["fee"] or 0))
            store_trade(tid, {"trade_id": trade_id, "strategy_id": str(cfg.get("STRATEGY", "unknown")),
                "strategy_version": str(cfg.get("STRATEGY_VERSION", "unknown")), "symbol": row["symbol"],
                "timeframe": str(cfg.get("INTERVAL", "unknown")), "direction": "buy",
                "entry_time": entry_time, "exit_time": float(row["ts"]), "entry_price": entry_price,
                "exit_price": float(row["price"]), "quantity": qty, "stop_loss": None,
                "take_profit": None, "fees": fees, "spread": float(meta.get("spread_rate", 0)),
                "slippage": float(meta.get("slippage_rate", 0)), "gross_pnl": gross, "net_pnl": net,
                "return_pct": float(meta.get("return_percentage", net / entry_value * 100)),
                "r_multiple": None, "hold_duration": max(0, float(row["ts"])-entry_time),
                "exit_reason": "execution_reconciliation", "confidence": None, "risk_multiplier": None,
                "research_approval_id": None, "market_regime": None,
                "config_fingerprint": _fingerprint(cfg)})
            queued += 1
    tid.flush()
    return {"reconciled": queued, "already_present": already_present, "skipped": skipped,
            "outbox": tid.status()}
