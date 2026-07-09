from __future__ import annotations
import json
import aiosqlite
from datetime import datetime, timezone
from typing import Optional
from config import DB_PATH

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS candles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument TEXT NOT NULL,
    interval TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    volume INTEGER, oi INTEGER,
    UNIQUE(instrument, interval, timestamp)
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    instrument TEXT,
    action TEXT,
    strike INTEGER,
    expiry TEXT,
    confidence INTEGER,
    reason TEXT,
    indicators TEXT,
    ai_response TEXT,
    decision_log TEXT,
    market_context TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_type TEXT DEFAULT 'paper',
    instrument TEXT,
    action TEXT,
    strike INTEGER,
    expiry TEXT,
    entry_time TEXT,
    entry_price REAL,
    exit_time TEXT,
    exit_price REAL,
    exit_reason TEXT,
    quantity INTEGER,
    pnl_raw REAL,
    pnl_final REAL,
    signal_id INTEGER REFERENCES signals(id),
    confidence INTEGER,
    entry_reason TEXT,
    capital_used REAL,
    capital_before REAL
);

CREATE TABLE IF NOT EXISTS learning_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    updated_at TEXT NOT NULL,
    rules TEXT NOT NULL,
    win_rate REAL,
    sharpe REAL,
    version INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    config TEXT,
    stats TEXT,
    total_trades INTEGER,
    win_rate REAL,
    profit_factor REAL,
    max_drawdown REAL,
    sharpe REAL
);
"""


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        for statement in CREATE_TABLES.strip().split(";"):
            s = statement.strip()
            if s:
                await db.execute(s)
        # Best-effort migrations: SQLite has no IF NOT EXISTS for ADD COLUMN
        for col_sql in (
            "ALTER TABLE signals ADD COLUMN decision_log TEXT",
            "ALTER TABLE signals ADD COLUMN market_context TEXT",
            "ALTER TABLE trades ADD COLUMN fees_total REAL",
            "ALTER TABLE trades ADD COLUMN slippage_cost REAL",
        ):
            try:
                await db.execute(col_sql)
            except Exception:
                pass  # column already exists
        await db.commit()
    print(f"[DB] Initialized at {DB_PATH}")


def _now_ist() -> str:
    import pytz
    return datetime.now(pytz.timezone("Asia/Kolkata")).isoformat()


async def insert_candle(instrument: str, interval: str, candle: list):
    ts, o, h, l, c, vol, oi = candle[0], candle[1], candle[2], candle[3], candle[4], candle[5], candle[6]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO candles (instrument,interval,timestamp,open,high,low,close,volume,oi) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (instrument, interval, str(ts), o, h, l, c, int(vol or 0), int(oi or 0)),
        )
        await db.commit()


async def insert_signal(signal: dict, decision_log: dict | None = None,
                         market_context: dict | None = None) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO signals (timestamp,instrument,action,strike,expiry,confidence,reason,"
            "indicators,ai_response,decision_log,market_context) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                _now_ist(),
                signal.get("instrument"),
                signal.get("action"),
                signal.get("strike"),
                signal.get("expiry"),
                signal.get("confidence"),
                signal.get("reasoning", ""),
                json.dumps(signal.get("indicators", {})),
                json.dumps(signal),
                json.dumps(decision_log) if decision_log else None,
                json.dumps(market_context) if market_context else None,
            ),
        )
        await db.commit()
        return cur.lastrowid


async def get_decision_log(signal_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT decision_log FROM signals WHERE id = ?", (signal_id,))
        row = await cur.fetchone()
        if row and row["decision_log"]:
            return json.loads(row["decision_log"])
        return None


async def insert_trade(trade: dict) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO trades (trade_type,instrument,action,strike,expiry,entry_time,entry_price,"
            "exit_time,exit_price,exit_reason,quantity,pnl_raw,pnl_final,signal_id,confidence,entry_reason,"
            "capital_used,capital_before) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                trade.get("trade_type", "paper"),
                trade.get("instrument"),
                trade.get("action"),
                trade.get("strike"),
                trade.get("expiry"),
                trade.get("entry_time"),
                trade.get("entry_price"),
                trade.get("exit_time"),
                trade.get("exit_price"),
                trade.get("exit_reason"),
                trade.get("quantity"),
                trade.get("pnl_raw"),
                trade.get("pnl_final"),
                trade.get("signal_id"),
                trade.get("confidence"),
                trade.get("entry_reason"),
                trade.get("capital_used"),
                trade.get("capital_before"),
            ),
        )
        await db.commit()
        return cur.lastrowid


async def update_trade_exit(trade_db_id: int, exit_time: str, exit_price: float,
                             exit_reason: str, pnl_raw: float, pnl_final: float,
                             fees_total: float | None = None, slippage_cost: float | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE trades SET exit_time=?, exit_price=?, exit_reason=?, pnl_raw=?, pnl_final=?, "
            "fees_total=?, slippage_cost=? WHERE id=?",
            (exit_time, exit_price, exit_reason, pnl_raw, pnl_final,
             fees_total, slippage_cost, trade_db_id),
        )
        await db.commit()


async def get_today_realized_pnl() -> float:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COALESCE(SUM(pnl_final),0) FROM trades "
            "WHERE date(entry_time) = date('now','localtime') AND exit_time IS NOT NULL"
        )
        row = await cur.fetchone()
        return float(row[0]) if row else 0.0


async def get_total_realized_pnl() -> float:
    """Sum of pnl_final across ALL closed trades ever — for persistent capital tracking."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COALESCE(SUM(pnl_final),0) FROM trades WHERE exit_time IS NOT NULL"
        )
        row = await cur.fetchone()
        return float(row[0]) if row else 0.0


async def get_today_trades() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM trades WHERE date(entry_time) = date('now','localtime') ORDER BY entry_time"
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_trades(days: int = 30, completed_only: bool = False) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        extra = "AND exit_time IS NOT NULL" if completed_only else ""
        cur = await db.execute(
            f"SELECT * FROM trades WHERE entry_time >= datetime('now', ?) {extra} ORDER BY entry_time",
            (f"-{days} days",),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_latest_rules() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT rules FROM learning_rules ORDER BY updated_at DESC LIMIT 1"
        )
        row = await cur.fetchone()
        if row:
            return json.loads(row["rules"])
        return {}


async def save_learning_rules(rules: dict, stats: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO learning_rules (updated_at,rules,win_rate,sharpe,version) VALUES (?,?,?,?,?)",
            (
                _now_ist(),
                json.dumps(rules),
                stats.get("win_rate", 0.0),
                stats.get("sharpe", 0.0),
                1,
            ),
        )
        await db.commit()


async def save_backtest_run(config: dict, stats: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO backtest_runs (run_at,config,stats,total_trades,win_rate,profit_factor,max_drawdown,sharpe) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                _now_ist(),
                json.dumps(config),
                json.dumps(stats),
                stats.get("total_trades", 0),
                stats.get("win_rate", 0.0),
                stats.get("profit_factor", 0.0),
                stats.get("max_drawdown", 0.0),
                stats.get("sharpe", 0.0),
            ),
        )
        await db.commit()
