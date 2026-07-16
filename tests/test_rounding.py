import os
import sys
# ensure package path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from mega_trading_bot import ExchangeManager, normalize_symbol


def test_rounding_fallback():
    cfg = {"EXCHANGE": "binance"}
    em = ExchangeManager(cfg)
    # no market loaded; rounding should not raise
    r = em.round_amount("BTCUSDT", 0.123456789)
    assert r <= 0.123456789
    p = em.round_price("BTCUSDT", 12345.6789)
    assert isinstance(p, float)
