import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from mega_trading_bot import ExchangeManager


def test_preflight_with_mock_market():
    cfg = {"EXCHANGE": "binance"}
    em = ExchangeManager(cfg)
    # monkeypatch get_market_info to return custom limits
    def fake_info(symbol):
        return {"limits": {"amount": {"min": 0.001, "max": 100}, "cost": {"min": 10}}}
    em.get_market_info = fake_info
    ok, msg = em.preflight_validate("BTCUSDT", 0.0005, 20000)
    assert not ok
    ok2, msg2 = em.preflight_validate("BTCUSDT", 0.001, 20000)
    assert ok2
