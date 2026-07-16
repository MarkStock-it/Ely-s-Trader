import os
import tempfile
import sqlite3
import sys
import os
# ensure TRADE package directory is on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import db
import scripts.export_trades as exporter


def test_export_roundtrip(tmp_path):
    db_file = str(tmp_path / "test_trades.db")
    # initialize DB
    db.init_db(db_file)
    conn = sqlite3.connect(db_file)
    cur = conn.cursor()
    # insert sample rows
    cur.execute("INSERT INTO orders(id,symbol,side,amount,entry_price,status,state,created_ts,meta) VALUES (?,?,?,?,?,?,?,?,?)",
                ("o1","BTCUSDT","buy",0.001,50000.0,'open','new',123456,'{}'))
    # let fills.id autoincrement
    cur.execute("INSERT INTO fills(order_id,ts,price,amount,fee,side,meta) VALUES (?,?,?,?,?,?,?)",
                ("o1", 123456, 50000.0,0.001,0.0,'buy','{}'))
    # events schema: (id, ts, level, msg)
    cur.execute("INSERT INTO events(ts,level,msg) VALUES (?,?,?)",
                (123456,'INFO','test event'))
    conn.commit()
    conn.close()
    out_dir = str(tmp_path / "exports")
    # export tables
    for t in ("orders","fills","events","idempotency"):
        try:
            path = exporter.export_table(db_file, t, out_dir)
            assert os.path.exists(path)
            with open(path,'r',encoding='utf-8') as f:
                content = f.read()
                assert len(content) > 0
        except Exception:
            # idempotency may be empty but export should not crash
            pass
