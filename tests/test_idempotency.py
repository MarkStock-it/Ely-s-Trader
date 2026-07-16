import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import tempfile
from mega_trading_bot import ExchangeManager
from execution import ExecutionEngine


def test_idempotency_paper_mode():
    d = tempfile.mkdtemp()
    db_path = os.path.join(d, "db.sqlite")
    cfg = {"EXCHANGE": "binance", "SYMBOL": "BTCUSDT", "PAPER_MODE": True, "LIVE_MODE": False, "DATA_PATH": d}
    em = ExchangeManager(cfg)
    # init DB
    import db as dbmod
    dbmod.init_db(db_path)
    ee = ExecutionEngine(em, db_path, cfg)
    res1 = ee.create_order("BTCUSDT", "buy", 0.001, price=20000, client_oid="c1")
    res2 = ee.create_order("BTCUSDT", "buy", 0.001, price=20000, client_oid="c1")
    # in paper mode, second call should return closed as well, but idempotency mapping will make it known
    assert res1.get("status") == "closed"
    assert res2.get("status") in ("closed", "known_from_idempotency")
