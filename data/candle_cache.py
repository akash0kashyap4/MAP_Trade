"""
Sync SQLite cache for candle data.
Uses sqlite3 (not aiosqlite) so the backtest engine and data_loader
can read/write without an async event loop.
"""
from __future__ import annotations
import sqlite3
from config import DB_PATH

_CANDLES_DDL = """
CREATE TABLE IF NOT EXISTS candles (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument TEXT NOT NULL,
    interval   TEXT NOT NULL,
    timestamp  TEXT NOT NULL,
    open  REAL, high REAL, low REAL, close REAL,
    volume INTEGER, oi INTEGER,
    UNIQUE(instrument, interval, timestamp)
);
"""

def _ensure_table():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(_CANDLES_DDL)
        conn.commit()

_ensure_table()


def save_candles(instrument_key: str, candles: list):
    """Bulk-insert candles into the candles table. Skips duplicates."""
    if not candles:
        return
    rows = []
    for c in candles:
        if len(c) < 5:
            continue
        rows.append((
            instrument_key,
            "1minute",
            str(c[0]),
            float(c[1]), float(c[2]), float(c[3]), float(c[4]),
            int(c[5]) if len(c) > 5 and c[5] else 0,
            int(c[6]) if len(c) > 6 and c[6] else 0,
        ))
    if not rows:
        return
    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO candles "
            "(instrument, interval, timestamp, open, high, low, close, volume, oi) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()


def get_candles(instrument_key: str, date_str: str) -> list:
    """Fetch cached 1-min candles for an instrument on a given date. Returns [] if not cached."""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "SELECT timestamp, open, high, low, close, volume, oi "
            "FROM candles WHERE instrument=? AND interval='1minute' AND date(timestamp)=? "
            "ORDER BY timestamp",
            (instrument_key, date_str),
        )
        rows = cur.fetchall()
    return [[r[0], r[1], r[2], r[3], r[4], r[5], r[6]] for r in rows]


def has_candles(instrument_key: str, date_str: str) -> bool:
    """Return True if at least 10 candles are cached for this instrument+date."""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "SELECT COUNT(*) FROM candles "
            "WHERE instrument=? AND interval='1minute' AND date(timestamp)=?",
            (instrument_key, date_str),
        )
        return (cur.fetchone()[0] or 0) >= 10


def get_cache_stats() -> dict:
    """Return summary of what's in the candle cache."""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "SELECT instrument, COUNT(DISTINCT date(timestamp)) as days, COUNT(*) as candles "
            "FROM candles GROUP BY instrument ORDER BY days DESC"
        )
        rows = cur.fetchall()
    return [{"instrument": r[0], "days": r[1], "candles": r[2]} for r in rows]
