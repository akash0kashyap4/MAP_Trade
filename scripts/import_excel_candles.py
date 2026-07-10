"""
Import 1-min NIFTY candles from Excel into the local SQLite candle cache.

Usage (on Droplet):
    pip install openpyxl   # if not already installed
    python3 scripts/import_excel_candles.py /path/to/nifty_1y_1min.xlsx

Expected Excel columns: Date | Time | Open | High | Low | Close | Volume
"""
from __future__ import annotations
import sys
import sqlite3
import os

# Run from repo root so config imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DB_PATH

INSTRUMENT_KEY = "NSE_INDEX|Nifty 50"
INTERVAL       = "1minute"


def _ensure_table(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candles (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            instrument TEXT NOT NULL,
            interval   TEXT NOT NULL,
            timestamp  TEXT NOT NULL,
            open  REAL, high REAL, low REAL, close REAL,
            volume INTEGER, oi INTEGER,
            UNIQUE(instrument, interval, timestamp)
        )
    """)
    conn.commit()


def import_excel(xlsx_path: str):
    try:
        import openpyxl
    except ImportError:
        print("openpyxl not found. Run: pip install openpyxl")
        sys.exit(1)

    print(f"Reading {xlsx_path} …")
    wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    headers = [str(h).strip() for h in rows[0]]
    print(f"Columns: {headers}")
    print(f"Total data rows: {len(rows) - 1:,}")

    # Find column indices
    def col(name):
        return headers.index(name)

    idx_date   = col("Date")
    idx_time   = col("Time")
    idx_open   = col("Open")
    idx_high   = col("High")
    idx_low    = col("Low")
    idx_close  = col("Close")
    idx_volume = col("Volume")

    records = []
    skipped = 0
    for row in rows[1:]:
        try:
            date_val = str(row[idx_date]).strip()
            time_val = str(row[idx_time]).strip()

            # Normalise: some cells may be datetime objects
            if hasattr(row[idx_date], 'strftime'):
                date_val = row[idx_date].strftime("%Y-%m-%d")
            if hasattr(row[idx_time], 'strftime'):
                time_val = row[idx_time].strftime("%H:%M:%S")

            # Build IST timestamp string
            ts = f"{date_val}T{time_val}+05:30"

            o = float(row[idx_open])
            h = float(row[idx_high])
            l = float(row[idx_low])
            c = float(row[idx_close])
            v = int(row[idx_volume] or 0)

            records.append((INSTRUMENT_KEY, INTERVAL, ts, o, h, l, c, v, 0))
        except Exception as e:
            skipped += 1
            continue

    print(f"Parsed {len(records):,} candles ({skipped} skipped)")

    print(f"Inserting into {DB_PATH} …")
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_table(conn)
        conn.executemany(
            "INSERT OR IGNORE INTO candles "
            "(instrument, interval, timestamp, open, high, low, close, volume, oi) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            records,
        )
        conn.commit()

        cur = conn.execute(
            "SELECT COUNT(*) FROM candles WHERE instrument=? AND interval=?",
            (INSTRUMENT_KEY, INTERVAL)
        )
        total = cur.fetchone()[0]

    print(f"Done. Total 1-min NIFTY candles in DB: {total:,}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/import_excel_candles.py /path/to/nifty_1y_1min.xlsx")
        sys.exit(1)
    import_excel(sys.argv[1])
