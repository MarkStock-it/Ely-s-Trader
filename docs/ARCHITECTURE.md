# Architecture Overview

Components:

- MarketDataManager: Polls or subscribes to exchange OHLCV/tickers and fans out to strategies and monitors.
- Strategy: Consumes market data, emits desired actions (signals) to the ExecutionEngine.
- ExecutionEngine: Idempotent order placement, preflight validation, rounding and retries. Persists orders/fills to SQLite.
- OrderReconciler: Background worker that polls exchange for order/trade status and reconciles with DB (handles partial fills).
- PositionMonitor: Enforces SL/TP and trailing stops by triggering ExecutionEngine actions.
- SQLite DB: Transactional persistence for orders, fills, events, idempotency mapping, audit trail.
- Web UI (Flask): Health endpoints, metrics endpoint, and simple status pages.
- Prometheus: Scrapes `/metrics` for counters/gauges.
- TelegramClient: Alerting channel for incidents and trade notifications.
- Backtester / Simulation: Offline engine using historical OHLCV from `MarketDataManager`.

Data flows:

1. Market data -> Strategy -> ExecutionEngine -> Exchange
2. Exchange fills -> OrderReconciler -> SQLite DB -> PositionMonitor
3. Execution events -> Audit logs -> Web UI / Alerts

