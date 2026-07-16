"""Export orders/fills/events from the SQLite DB to CSV for compliance.

Usage:
    python scripts/export_trades.py --db data/mega_trades.db --out exports/
"""
import os
import argparse
import sqlite3
import csv


def export_table(db_path: str, table: str, out_dir: str):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM {table}")
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, f"{table}.csv")
    with open(out_file, "w", newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)
    conn.close()
    return out_file


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=os.path.join("data", "mega_trades.db"))
    p.add_argument("--out", default="exports")
    args = p.parse_args()
    for t in ("orders", "fills", "events", "idempotency"):
        try:
            path = export_table(args.db, t, args.out)
            print("Exported", t, "->", path)
        except Exception as e:
            print("Failed to export", t, e)
