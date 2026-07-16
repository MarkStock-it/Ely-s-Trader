"""Central Prometheus metrics for the trading bot.

Defines counters/gauges safely so other modules can import them.
If `prometheus_client` is not available the symbols are no-op placeholders.
"""
import time
try:
    from prometheus_client import Counter, Gauge, Summary
    ORDER_ATTEMPTS = Counter("mtb_order_attempts_total", "Order attempts total")
    ORDER_FAILURES = Counter("mtb_order_failures_total", "Order failures total")
    ORDER_SUCCESSES = Counter("mtb_order_successes_total", "Order successes total")
    FILLS = Counter("mtb_fills_total", "Fills recorded total")
    RECONCILED_ORDERS = Counter("mtb_reconciled_orders_total", "Reconciled orders total")
    OPEN_ORDERS_GAUGE = Gauge("mtb_open_orders", "Number of open orders observed")
    LAST_RECONCILE = Gauge("mtb_last_reconcile_timestamp", "Last reconcile unix timestamp")
    EXECUTION_LATENCY = Summary("mtb_execution_latency_seconds", "Execution latency seconds")
    # Position / MarketData metrics
    OPEN_POSITIONS_GAUGE = Gauge("mtb_open_positions", "Number of open positions")
    POSITION_CLOSES = Counter("mtb_position_closes_total", "Positions closed total")
    POSITION_MONITOR_ERRORS = Counter("mtb_position_monitor_errors_total", "Position monitor errors total")
    MD_FETCHES = Counter("mtb_md_fetches_total", "Market data fetch operations total")
    MD_BUFFER_SIZE = Gauge("mtb_md_buffer_size", "Market data buffer size per symbol")
    LAST_MD_FETCH = Gauge("mtb_last_md_fetch_timestamp", "Last market data fetch unix timestamp")
    PROM_AVAILABLE = True
except Exception:
    # No-op fallbacks
    class _Noop:
        def inc(self, *a, **k):
            return None
        def set(self, *a, **k):
            return None
        def observe(self, *a, **k):
            return None

    ORDER_ATTEMPTS = ORDER_FAILURES = ORDER_SUCCESSES = FILLS = RECONCILED_ORDERS = _Noop()
    OPEN_ORDERS_GAUGE = LAST_RECONCILE = EXECUTION_LATENCY = _Noop()
    OPEN_POSITIONS_GAUGE = POSITION_CLOSES = POSITION_MONITOR_ERRORS = MD_FETCHES = MD_BUFFER_SIZE = LAST_MD_FETCH = _Noop()
    PROM_AVAILABLE = False

__all__ = [
    "ORDER_ATTEMPTS",
    "ORDER_FAILURES",
    "ORDER_SUCCESSES",
    "FILLS",
    "RECONCILED_ORDERS",
    "OPEN_ORDERS_GAUGE",
    "LAST_RECONCILE",
    "EXECUTION_LATENCY",
    "OPEN_POSITIONS_GAUGE",
    "POSITION_CLOSES",
    "POSITION_MONITOR_ERRORS",
    "MD_FETCHES",
    "MD_BUFFER_SIZE",
    "LAST_MD_FETCH",
    "PROM_AVAILABLE",
]
