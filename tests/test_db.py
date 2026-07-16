import os
import sys
import tempfile
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import db


def test_init_db_and_order_log():
    d = tempfile.mkdtemp()
    path = os.path.join(d, "test_trades.db")
    db.init_db(path)
    order = {"id": "o1", "symbol": "BTCUSDT", "side": "buy", "amount": 0.1, "entry_price": 1000.0, "status": "open", "created_ts": 0}
    db.log_order(path, order)
    open_orders = db.get_open_orders(path)
    assert any(o["id"] == "o1" for o in open_orders)
    db.update_order_status(path, "o1", "closed", "closed")
    open_orders = db.get_open_orders(path)
    assert not any(o["id"] == "o1" for o in open_orders)
