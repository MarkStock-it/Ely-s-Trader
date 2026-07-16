import sys
import os
# Ensure the repo `TRADE` package directory is on sys.path for tests
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import metrics


def test_metrics_noop_and_calls():
    # Ensure calling metric methods does not raise, both when prometheus is installed or not.
    try:
        metrics.ORDER_ATTEMPTS.inc()
        metrics.ORDER_FAILURES.inc()
        metrics.FILLS.inc()
        metrics.RECONCILED_ORDERS.inc()
        metrics.OPEN_ORDERS_GAUGE.set(0)
        metrics.OPEN_POSITIONS_GAUGE.set(0)
        metrics.MD_FETCHES.inc()
        metrics.MD_BUFFER_SIZE.set(0)
        metrics.LAST_MD_FETCH.set(0)
    except Exception as e:
        raise AssertionError("Metric calls raised an exception") from e
    assert isinstance(metrics.PROM_AVAILABLE, bool)
