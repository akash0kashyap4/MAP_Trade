from __future__ import annotations
import json
import logging
import os
import socket
from datetime import datetime
import pytz

from config import DB_PATH as _DEFAULT_DB_PATH

log = logging.getLogger(__name__)

# Force IPv4 (Vercel does not support IPv6 outbound)
_orig_getaddrinfo = socket.getaddrinfo
def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = _ipv4_getaddrinfo

DATABASE_URL = os.getenv("DATABASE_URL")
_USE_SQLITE   = not DATABASE_URL
_SQLITE_PATH  = _DEFAULT_DB_PATH

# ── SQLite DDL (? params, AUTOINCREMENT) ─────────────────────────────────────
_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS candles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument TEXT NOT NULL, interval TEXT NOT NULL, timestamp TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume INTEGER, oi INTEGER,
    UNIQUE(instrument, interval, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_candles_lookup ON candles(instrument, interval, timestamp);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL, instrument TEXT, action TEXT, strike INTEGER,
    expiry TEXT, confidence INTEGER, reason TEXT, indicators TEXT,
    ai_response TEXT, decision_log TEXT, market_context TEXT,
    signal_quality TEXT
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_type TEXT DEFAULT 'paper', instrument TEXT, action TEXT,
    strike INTEGER, expiry TEXT, entry_time TEXT, entry_price REAL,
    exit_time TEXT, exit_price REAL, exit_reason TEXT, quantity INTEGER,
    pnl_raw REAL, pnl_final REAL, signal_id INTEGER, confidence INTEGER,
    entry_reason TEXT, capital_used REAL, capital_before REAL,
    fees_total REAL, slippage_cost REAL
);
CREATE TABLE IF NOT EXISTS learning_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    updated_at TEXT NOT NULL, rules TEXT NOT NULL,
    win_rate REAL, sharpe REAL, version INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL, config TEXT, stats TEXT,
    total_trades INTEGER, win_rate REAL,
    profit_factor REAL, max_drawdown REAL, sharpe REAL
);
CREATE TABLE IF NOT EXISTS daily_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date TEXT NOT NULL UNIQUE, mode TEXT DEFAULT 'paper',
    report TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    news_date TEXT NOT NULL, fetched_at TEXT NOT NULL,
    source TEXT, headline TEXT, url TEXT, sentiment TEXT,
    UNIQUE(news_date, headline)
);
CREATE TABLE IF NOT EXISTS news_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    news_date TEXT NOT NULL UNIQUE, analysis TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS knowledge_base (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kdate TEXT NOT NULL, category TEXT NOT NULL, lesson TEXT NOT NULL,
    source TEXT, confidence INTEGER DEFAULT 5, created_at TEXT NOT NULL,
    UNIQUE(category, lesson)
);
CREATE TABLE IF NOT EXISTS ai_strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE, created_date TEXT NOT NULL,
    rationale TEXT, rules TEXT, status TEXT DEFAULT 'PROPOSED',
    stats TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS ai_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sdate TEXT NOT NULL, category TEXT, suggestion TEXT NOT NULL,
    priority TEXT DEFAULT 'MEDIUM', status TEXT DEFAULT 'NEW',
    created_at TEXT NOT NULL, UNIQUE(suggestion)
);
"""

# ── Postgres DDL ($N params, SERIAL) ─────────────────────────────────────────
_PG_DDL = """
CREATE TABLE IF NOT EXISTS candles (
    id SERIAL PRIMARY KEY, instrument TEXT NOT NULL, interval TEXT NOT NULL,
    timestamp TEXT NOT NULL, open REAL, high REAL, low REAL, close REAL,
    volume INTEGER, oi INTEGER, UNIQUE(instrument, interval, timestamp)
);
CREATE TABLE IF NOT EXISTS signals (
    id SERIAL PRIMARY KEY, timestamp TEXT NOT NULL, instrument TEXT, action TEXT,
    strike INTEGER, expiry TEXT, confidence INTEGER, reason TEXT, indicators TEXT,
    ai_response TEXT, decision_log TEXT, market_context TEXT,
    signal_quality TEXT
);
CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY, trade_type TEXT DEFAULT 'paper', instrument TEXT,
    action TEXT, strike INTEGER, expiry TEXT, entry_time TEXT, entry_price REAL,
    exit_time TEXT, exit_price REAL, exit_reason TEXT, quantity INTEGER,
    pnl_raw REAL, pnl_final REAL, signal_id INTEGER REFERENCES signals(id),
    confidence INTEGER, entry_reason TEXT, capital_used REAL, capital_before REAL,
    fees_total REAL, slippage_cost REAL
);
CREATE TABLE IF NOT EXISTS learning_rules (
    id SERIAL PRIMARY KEY, updated_at TEXT NOT NULL, rules TEXT NOT NULL,
    win_rate REAL, sharpe REAL, version INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS backtest_runs (
    id SERIAL PRIMARY KEY, run_at TEXT NOT NULL, config TEXT, stats TEXT,
    total_trades INTEGER, win_rate REAL, profit_factor REAL, max_drawdown REAL, sharpe REAL
);
CREATE TABLE IF NOT EXISTS daily_reports (
    id SERIAL PRIMARY KEY, report_date TEXT NOT NULL UNIQUE, mode TEXT DEFAULT 'paper',
    report TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS news_items (
    id SERIAL PRIMARY KEY, news_date TEXT NOT NULL, fetched_at TEXT NOT NULL,
    source TEXT, headline TEXT, url TEXT, sentiment TEXT,
    UNIQUE(news_date, headline)
);
CREATE TABLE IF NOT EXISTS news_analysis (
    id SERIAL PRIMARY KEY, news_date TEXT NOT NULL UNIQUE, analysis TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS knowledge_base (
    id SERIAL PRIMARY KEY, kdate TEXT NOT NULL, category TEXT NOT NULL, lesson TEXT NOT NULL,
    source TEXT, confidence INTEGER DEFAULT 5, created_at TEXT NOT NULL,
    UNIQUE(category, lesson)
);
CREATE TABLE IF NOT EXISTS ai_strategies (
    id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_date TEXT NOT NULL,
    rationale TEXT, rules TEXT, status TEXT DEFAULT 'PROPOSED',
    stats TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS ai_suggestions (
    id SERIAL PRIMARY KEY, sdate TEXT NOT NULL, category TEXT, suggestion TEXT NOT NULL,
    priority TEXT DEFAULT 'MEDIUM', status TEXT DEFAULT 'NEW',
    created_at TEXT NOT NULL, UNIQUE(suggestion)
);
"""

_pool   = None   # asyncpg pool (Postgres mode)
_warned = False  # suppress repeated DB-missing warnings

def _now_ist() -> str:
    return datetime.now(pytz.timezone("Asia/Kolkata")).isoformat()


# ── Postgres helpers ──────────────────────────────────────────────────────────

async def _pg_pool():
    global _pool
    if _pool is None:
        import asyncpg
        _pool = await asyncpg.create_pool(
            DATABASE_URL, statement_cache_size=0, min_size=1, max_size=5, command_timeout=30,
        )
    return _pool


# ── SQLite helpers ────────────────────────────────────────────────────────────

def _sqlite_conn():
    """Return an aiosqlite connection context — use `async with _sqlite_conn() as db`.
    Do NOT await it first: awaiting starts the worker thread, and entering the
    context manager afterwards starts it again ("threads can only be started
    once" on aiosqlite >= 0.20), which broke every DB operation."""
    import aiosqlite
    return aiosqlite.connect(_SQLITE_PATH)


# ── Public init ───────────────────────────────────────────────────────────────

async def init_db():
    if _USE_SQLITE:
        try:
            async with _sqlite_conn() as db:
                for stmt in _SQLITE_DDL.strip().split(";"):
                    s = stmt.strip()
                    if s:
                        await db.execute(s)
                # Dynamic SQLite migration for missing columns
                try:
                    async with db.execute("PRAGMA table_info(signals)") as cur:
                        cols = [row[1] for row in await cur.fetchall()]
                        if "signal_quality" not in cols:
                            await db.execute("ALTER TABLE signals ADD COLUMN signal_quality TEXT")
                except Exception as e:
                    print(f"[DB] SQLite migration error (signal_quality): {e}")

                # Create indexes for analytics performance
                try:
                    await db.execute("CREATE INDEX IF NOT EXISTS idx_trades_entry ON trades(entry_time)")
                    await db.execute("CREATE INDEX IF NOT EXISTS idx_trades_exit ON trades(exit_time)")
                except Exception as e:
                    print(f"[DB] SQLite index creation error: {e}")

                await db.commit()
            print(f"[DB] Initialized SQLite DB at {_SQLITE_PATH}")
        except Exception as e:
            print(f"[DB] SQLite init error: {e}")
    else:
        try:
            pool = await _pg_pool()
            async with pool.acquire() as db:
                for stmt in _PG_DDL.strip().split(";"):
                    s = stmt.strip()
                    if s:
                        await db.execute(s)
                # Dynamic Postgres migration for missing columns
                try:
                    res = await db.fetch("SELECT column_name FROM information_schema.columns WHERE table_name='signals'")
                    cols = [r["column_name"] for r in res]
                    if "signal_quality" not in cols:
                        await db.execute("ALTER TABLE signals ADD COLUMN signal_quality TEXT")
                except Exception as e:
                    print(f"[DB] Postgres migration error (signal_quality): {e}")

                # Create indexes for analytics performance
                try:
                    await db.execute("CREATE INDEX IF NOT EXISTS idx_trades_entry ON trades(entry_time)")
                    await db.execute("CREATE INDEX IF NOT EXISTS idx_trades_exit ON trades(exit_time)")
                except Exception as e:
                    print(f"[DB] Postgres index creation error: {e}")
            print("[DB] Initialized Postgres DB")
        except Exception as e:
            print(f"[DB] WARNING: Could not connect to Postgres: {e}")
            print("[DB] App will continue without DB — check DATABASE_URL env var.")


# ── insert_candle ─────────────────────────────────────────────────────────────

async def insert_candle(instrument: str, interval: str, candle: list):
    ts, o, h, low, c, vol, oi = candle[0], candle[1], candle[2], candle[3], candle[4], candle[5], candle[6]
    if _USE_SQLITE:
        try:
            async with _sqlite_conn() as db:
                await db.execute(
                    "INSERT OR IGNORE INTO candles (instrument,interval,timestamp,open,high,low,close,volume,oi) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (instrument, interval, str(ts), o, h, low, c, int(vol or 0), int(oi or 0))
                )
                await db.commit()
        except Exception as e:
            log.debug("[insert_candle] SQLite error: %s", e)
    else:
        try:
            pool = await _pg_pool()
            async with pool.acquire() as db:
                await db.execute(
                    "INSERT INTO candles (instrument,interval,timestamp,open,high,low,close,volume,oi) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT (instrument, interval, timestamp) DO NOTHING",
                    instrument, interval, str(ts), o, h, low, c, int(vol or 0), int(oi or 0)
                )
        except Exception as e:
            log.debug("[insert_candle] PG error: %s", e)


# ── insert_signal ─────────────────────────────────────────────────────────────

async def insert_signal(signal: dict, decision_log: dict | None = None,
                        market_context: dict | None = None, signal_quality: str | None = None) -> int:
    vals = (
        _now_ist(), signal.get("instrument"), signal.get("action"),
        signal.get("strike"), signal.get("expiry"), signal.get("confidence"),
        signal.get("reasoning", ""),
        json.dumps(signal.get("indicators", {})),
        json.dumps(signal),
        json.dumps(decision_log) if decision_log else None,
        json.dumps(market_context) if market_context else None,
        signal_quality,
    )
    if _USE_SQLITE:
        try:
            async with _sqlite_conn() as db:
                cur = await db.execute(
                    "INSERT INTO signals (timestamp,instrument,action,strike,expiry,confidence,reason,"
                    "indicators,ai_response,decision_log,market_context,signal_quality) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    vals
                )
                await db.commit()
                return cur.lastrowid or 0
        except Exception as e:
            log.warning("[insert_signal] SQLite error: %s", e)
            return 0
    else:
        try:
            pool = await _pg_pool()
            async with pool.acquire() as db:
                row = await db.fetchrow(
                    "INSERT INTO signals (timestamp,instrument,action,strike,expiry,confidence,reason,"
                    "indicators,ai_response,decision_log,market_context,signal_quality) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12) RETURNING id",
                    *vals
                )
                return row["id"]
        except Exception as e:
            log.warning("[insert_signal] PG error: %s", e)
            return 0


# ── get_decision_log ──────────────────────────────────────────────────────────

async def get_decision_log(signal_id: int) -> dict | None:
    if _USE_SQLITE:
        try:
            async with _sqlite_conn() as db:
                db.row_factory = _sqlite_dict_factory
                async with db.execute("SELECT decision_log FROM signals WHERE id=?", (signal_id,)) as cur:
                    row = await cur.fetchone()
                    if row and row["decision_log"]:
                        return json.loads(row["decision_log"])
        except Exception as e:
            log.debug("[get_decision_log] SQLite error: %s", e)
        return None
    else:
        try:
            pool = await _pg_pool()
            async with pool.acquire() as db:
                row = await db.fetchrow("SELECT decision_log FROM signals WHERE id=$1", signal_id)
                if row and row["decision_log"]:
                    return json.loads(row["decision_log"])
        except Exception as e:
            log.debug("[get_decision_log] PG error: %s", e)
        return None


# ── insert_trade ──────────────────────────────────────────────────────────────

async def insert_trade(trade: dict) -> int:
    vals = (
        trade.get("trade_type", "paper"), trade.get("instrument"), trade.get("action"),
        trade.get("strike"), trade.get("expiry"), trade.get("entry_time"),
        trade.get("entry_price"), trade.get("exit_time"), trade.get("exit_price"),
        trade.get("exit_reason"), trade.get("quantity"), trade.get("pnl_raw"),
        trade.get("pnl_final"), trade.get("signal_id"), trade.get("confidence"),
        trade.get("entry_reason"), trade.get("capital_used"), trade.get("capital_before"),
    )
    if _USE_SQLITE:
        try:
            async with _sqlite_conn() as db:
                cur = await db.execute(
                    "INSERT INTO trades (trade_type,instrument,action,strike,expiry,entry_time,entry_price,"
                    "exit_time,exit_price,exit_reason,quantity,pnl_raw,pnl_final,signal_id,confidence,"
                    "entry_reason,capital_used,capital_before) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    vals
                )
                await db.commit()
                return cur.lastrowid or 0
        except Exception as e:
            log.warning("[insert_trade] SQLite error: %s", e)
            return 0
    else:
        try:
            pool = await _pg_pool()
            async with pool.acquire() as db:
                row = await db.fetchrow(
                    "INSERT INTO trades (trade_type,instrument,action,strike,expiry,entry_time,entry_price,"
                    "exit_time,exit_price,exit_reason,quantity,pnl_raw,pnl_final,signal_id,confidence,"
                    "entry_reason,capital_used,capital_before) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,"
                    "$13,$14,$15,$16,$17,$18) RETURNING id",
                    *vals
                )
                return row["id"]
        except Exception as e:
            log.warning("[insert_trade] PG error: %s", e)
            return 0


# ── update_trade_exit ─────────────────────────────────────────────────────────

async def update_trade_exit(trade_db_id: int, exit_time: str, exit_price: float,
                            exit_reason: str, pnl_raw: float, pnl_final: float,
                            fees_total: float | None = None, slippage_cost: float | None = None):
    if _USE_SQLITE:
        try:
            async with _sqlite_conn() as db:
                await db.execute(
                    "UPDATE trades SET exit_time=?,exit_price=?,exit_reason=?,pnl_raw=?,pnl_final=?,"
                    "fees_total=?,slippage_cost=? WHERE id=?",
                    (exit_time, exit_price, exit_reason, pnl_raw, pnl_final,
                     fees_total, slippage_cost, trade_db_id)
                )
                await db.commit()
        except Exception as e:
            log.warning("[update_trade_exit] SQLite error: %s", e)
    else:
        try:
            pool = await _pg_pool()
            async with pool.acquire() as db:
                await db.execute(
                    "UPDATE trades SET exit_time=$1,exit_price=$2,exit_reason=$3,pnl_raw=$4,pnl_final=$5,"
                    "fees_total=$6,slippage_cost=$7 WHERE id=$8",
                    exit_time, exit_price, exit_reason, pnl_raw, pnl_final,
                    fees_total, slippage_cost, trade_db_id
                )
        except Exception as e:
            log.warning("[update_trade_exit] PG error: %s", e)


# ── read helpers ──────────────────────────────────────────────────────────────

def _sqlite_dict_factory(cursor, row):
    fields = [col[0] for col in cursor.description]
    return {k: v for k, v in zip(fields, row)}


async def get_today_realized_pnl() -> float:
    if _USE_SQLITE:
        try:
            async with _sqlite_conn() as db:
                async with db.execute(
                    "SELECT COALESCE(SUM(pnl_final),0) as total FROM trades "
                    "WHERE date(entry_time)=date('now') AND exit_time IS NOT NULL"
                ) as cur:
                    row = await cur.fetchone()
                    return float(row[0]) if row else 0.0
        except Exception:
            return 0.0
    else:
        try:
            pool = await _pg_pool()
            async with pool.acquire() as db:
                row = await db.fetchrow(
                    "SELECT COALESCE(SUM(pnl_final),0) as total FROM trades "
                    "WHERE DATE(entry_time)=CURRENT_DATE AND exit_time IS NOT NULL"
                )
                return float(row["total"]) if row else 0.0
        except Exception:
            return 0.0


async def get_total_realized_pnl() -> float:
    if _USE_SQLITE:
        try:
            async with _sqlite_conn() as db:
                async with db.execute(
                    "SELECT COALESCE(SUM(pnl_final),0) as total FROM trades WHERE exit_time IS NOT NULL"
                ) as cur:
                    row = await cur.fetchone()
                    return float(row[0]) if row else 0.0
        except Exception:
            return 0.0
    else:
        try:
            pool = await _pg_pool()
            async with pool.acquire() as db:
                row = await db.fetchrow(
                    "SELECT COALESCE(SUM(pnl_final),0) as total FROM trades WHERE exit_time IS NOT NULL"
                )
                return float(row["total"]) if row else 0.0
        except Exception:
            return 0.0


async def get_today_trades() -> list:
    if _USE_SQLITE:
        try:
            async with _sqlite_conn() as db:
                db.row_factory = _sqlite_dict_factory
                async with db.execute(
                    "SELECT * FROM trades WHERE date(entry_time)=date('now') ORDER BY entry_time"
                ) as cur:
                    rows = await cur.fetchall()
                    return list(rows)
        except Exception as e:
            print(f"[trades/today] SQLite error: {e}")
            return []
    else:
        try:
            pool = await _pg_pool()
            async with pool.acquire() as db:
                rows = await db.fetch(
                    "SELECT * FROM trades WHERE DATE(entry_time)=CURRENT_DATE ORDER BY entry_time"
                )
                return [dict(r) for r in rows]
        except Exception as e:
            print(f"[trades/today] DB error: {e}")
            return []


async def get_open_trades() -> list:
    if _USE_SQLITE:
        try:
            async with _sqlite_conn() as db:
                db.row_factory = _sqlite_dict_factory
                async with db.execute(
                    "SELECT * FROM trades WHERE exit_time IS NULL ORDER BY entry_time"
                ) as cur:
                    rows = await cur.fetchall()
                    return list(rows)
        except Exception as e:
            print(f"[trades/open] SQLite error: {e}")
            return []
    else:
        try:
            pool = await _pg_pool()
            async with pool.acquire() as db:
                rows = await db.fetch(
                    "SELECT * FROM trades WHERE exit_time IS NULL ORDER BY entry_time"
                )
                return [dict(r) for r in rows]
        except Exception as e:
            print(f"[trades/open] DB error: {e}")
            return []


async def get_trades(days: int = 30, completed_only: bool = False) -> list:
    if _USE_SQLITE:
        try:
            extra = "AND exit_time IS NOT NULL" if completed_only else ""
            async with _sqlite_conn() as db:
                db.row_factory = _sqlite_dict_factory
                async with db.execute(
                    f"SELECT * FROM trades WHERE entry_time >= datetime('now','-{days} days') {extra} ORDER BY entry_time"
                ) as cur:
                    rows = await cur.fetchall()
                    return list(rows)
        except Exception as e:
            log.debug("[get_trades] SQLite error: %s", e)
            return []
    else:
        try:
            pool = await _pg_pool()
            async with pool.acquire() as db:
                extra = "AND exit_time IS NOT NULL" if completed_only else ""
                rows = await db.fetch(
                    f"SELECT * FROM trades WHERE CAST(entry_time AS TIMESTAMP)>=NOW()-INTERVAL '{int(days)} days' {extra} ORDER BY entry_time"
                )
                return [dict(r) for r in rows]
        except Exception as e:
            log.debug("[get_trades] PG error: %s", e)
            return []


async def get_latest_rules() -> dict:
    if _USE_SQLITE:
        try:
            async with _sqlite_conn() as db:
                async with db.execute(
                    "SELECT rules FROM learning_rules ORDER BY updated_at DESC LIMIT 1"
                ) as cur:
                    row = await cur.fetchone()
                    if row and row[0]:
                        return json.loads(row[0])
        except Exception as e:
            log.debug("[get_latest_rules] SQLite error: %s", e)
        return {}
    else:
        try:
            pool = await _pg_pool()
            async with pool.acquire() as db:
                row = await db.fetchrow(
                    "SELECT rules FROM learning_rules ORDER BY updated_at DESC LIMIT 1"
                )
                if row and row["rules"]:
                    return json.loads(row["rules"])
        except Exception as e:
            log.debug("[get_latest_rules] PG error: %s", e)
        return {}


async def save_learning_rules(rules: dict, stats: dict):
    vals = (_now_ist(), json.dumps(rules), stats.get("win_rate", 0.0), stats.get("sharpe", 0.0), 1)
    if _USE_SQLITE:
        try:
            async with _sqlite_conn() as db:
                await db.execute(
                    "INSERT INTO learning_rules (updated_at,rules,win_rate,sharpe,version) VALUES (?,?,?,?,?)", vals
                )
                await db.commit()
        except Exception as e:
            log.warning("[save_learning_rules] SQLite error: %s", e)
    else:
        try:
            pool = await _pg_pool()
            async with pool.acquire() as db:
                await db.execute(
                    "INSERT INTO learning_rules (updated_at,rules,win_rate,sharpe,version) VALUES ($1,$2,$3,$4,$5)", *vals
                )
        except Exception as e:
            log.warning("[save_learning_rules] PG error: %s", e)


async def save_backtest_run(config: dict, stats: dict):
    vals = (
        _now_ist(), json.dumps(config), json.dumps(stats),
        stats.get("total_trades", 0), stats.get("win_rate", 0.0),
        stats.get("profit_factor", 0.0), stats.get("max_drawdown", 0.0), stats.get("sharpe", 0.0),
    )
    if _USE_SQLITE:
        try:
            async with _sqlite_conn() as db:
                await db.execute(
                    "INSERT INTO backtest_runs (run_at,config,stats,total_trades,win_rate,profit_factor,max_drawdown,sharpe) "
                    "VALUES (?,?,?,?,?,?,?,?)", vals
                )
                await db.commit()
        except Exception as e:
            log.warning("[save_backtest_run] SQLite error: %s", e)
    else:
        try:
            pool = await _pg_pool()
            async with pool.acquire() as db:
                await db.execute(
                    "INSERT INTO backtest_runs (run_at,config,stats,total_trades,win_rate,profit_factor,max_drawdown,sharpe) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)", *vals
                )
        except Exception as e:
            log.warning("[save_backtest_run] PG error: %s", e)


async def get_signal(signal_id: int) -> dict | None:
    if _USE_SQLITE:
        try:
            async with _sqlite_conn() as db:
                db.row_factory = _sqlite_dict_factory
                async with db.execute("SELECT * FROM signals WHERE id=?", (signal_id,)) as cur:
                    return await cur.fetchone()
        except Exception as e:
            log.warning("[get_signal] SQLite error: %s", e)
            return None
    else:
        try:
            pool = await _pg_pool()
            async with pool.acquire() as db:
                row = await db.fetchrow("SELECT * FROM signals WHERE id=$1", signal_id)
                return dict(row) if row else None
        except Exception as e:
            log.warning("[get_signal] PG error: %s", e)
            return None


async def get_trade(trade_id: int) -> dict | None:
    if _USE_SQLITE:
        try:
            async with _sqlite_conn() as db:
                db.row_factory = _sqlite_dict_factory
                async with db.execute("SELECT * FROM trades WHERE id=?", (trade_id,)) as cur:
                    return await cur.fetchone()
        except Exception as e:
            log.warning("[get_trade] SQLite error: %s", e)
            return None
    else:
        try:
            pool = await _pg_pool()
            async with pool.acquire() as db:
                row = await db.fetchrow("SELECT * FROM trades WHERE id=$1", trade_id)
                return dict(row) if row else None
        except Exception as e:
            log.warning("[get_trade] PG error: %s", e)
            return None


# ── Generic dual-backend helpers ──────────────────────────────────────────────
# SQL is written once with ? placeholders and ON CONFLICT clauses (supported by
# both SQLite >= 3.24 and Postgres); ? is converted to $N for asyncpg.

def _qmark_to_pg(sql: str) -> str:
    out, n = [], 0
    for ch in sql:
        if ch == "?":
            n += 1
            out.append(f"${n}")
        else:
            out.append(ch)
    return "".join(out)


async def _db_exec(sql: str, params: tuple = (), tag: str = "db_exec") -> None:
    if _USE_SQLITE:
        try:
            async with _sqlite_conn() as db:
                await db.execute(sql, params)
                await db.commit()
        except Exception as e:
            log.warning("[%s] SQLite error: %s", tag, e)
    else:
        try:
            pool = await _pg_pool()
            async with pool.acquire() as db:
                await db.execute(_qmark_to_pg(sql), *params)
        except Exception as e:
            log.warning("[%s] PG error: %s", tag, e)


async def _db_fetchall(sql: str, params: tuple = (), tag: str = "db_fetch") -> list[dict]:
    if _USE_SQLITE:
        try:
            async with _sqlite_conn() as db:
                db.row_factory = _sqlite_dict_factory
                async with db.execute(sql, params) as cur:
                    return list(await cur.fetchall())
        except Exception as e:
            log.warning("[%s] SQLite error: %s", tag, e)
            return []
    else:
        try:
            pool = await _pg_pool()
            async with pool.acquire() as db:
                rows = await db.fetch(_qmark_to_pg(sql), *params)
                return [dict(r) for r in rows]
        except Exception as e:
            log.warning("[%s] PG error: %s", tag, e)
            return []


async def _db_fetchone(sql: str, params: tuple = (), tag: str = "db_fetchone") -> dict | None:
    rows = await _db_fetchall(sql, params, tag)
    return rows[0] if rows else None


# ── Daily reports ─────────────────────────────────────────────────────────────

async def save_daily_report(report_date: str, mode: str, report: dict) -> None:
    await _db_exec(
        "INSERT INTO daily_reports (report_date,mode,report,created_at) VALUES (?,?,?,?) "
        "ON CONFLICT(report_date) DO UPDATE SET mode=excluded.mode, report=excluded.report, "
        "created_at=excluded.created_at",
        (report_date, mode, json.dumps(report), _now_ist()),
        tag="save_daily_report",
    )


async def get_daily_report(report_date: str) -> dict | None:
    row = await _db_fetchone(
        "SELECT * FROM daily_reports WHERE report_date=?", (report_date,), tag="get_daily_report"
    )
    if row and row.get("report"):
        try:
            row["report"] = json.loads(row["report"])
        except Exception:
            pass
    return row


async def get_daily_reports(limit: int = 30) -> list[dict]:
    rows = await _db_fetchall(
        "SELECT * FROM daily_reports ORDER BY report_date DESC LIMIT ?",
        (int(limit),), tag="get_daily_reports",
    )
    for r in rows:
        try:
            r["report"] = json.loads(r["report"])
        except Exception:
            pass
    return rows


# ── News ──────────────────────────────────────────────────────────────────────

async def save_news_items(news_date: str, items: list[dict]) -> None:
    now = _now_ist()
    for it in items:
        await _db_exec(
            "INSERT INTO news_items (news_date,fetched_at,source,headline,url,sentiment) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(news_date, headline) DO NOTHING",
            (news_date, now, it.get("source", ""), (it.get("headline") or "")[:300],
             it.get("url", ""), it.get("sentiment", "")),
            tag="save_news_items",
        )


async def get_news_items(news_date: str, limit: int = 50) -> list[dict]:
    return await _db_fetchall(
        "SELECT * FROM news_items WHERE news_date=? ORDER BY id DESC LIMIT ?",
        (news_date, int(limit)), tag="get_news_items",
    )


async def save_news_analysis(news_date: str, analysis: dict) -> None:
    await _db_exec(
        "INSERT INTO news_analysis (news_date,analysis,updated_at) VALUES (?,?,?) "
        "ON CONFLICT(news_date) DO UPDATE SET analysis=excluded.analysis, updated_at=excluded.updated_at",
        (news_date, json.dumps(analysis), _now_ist()),
        tag="save_news_analysis",
    )


async def get_news_analysis(news_date: str) -> dict | None:
    row = await _db_fetchone(
        "SELECT * FROM news_analysis WHERE news_date=?", (news_date,), tag="get_news_analysis"
    )
    if row and row.get("analysis"):
        try:
            return json.loads(row["analysis"])
        except Exception:
            return None
    return None


# ── Knowledge base ────────────────────────────────────────────────────────────

async def add_knowledge_entries(kdate: str, entries: list[dict], source: str = "") -> None:
    now = _now_ist()
    for e in entries:
        lesson = (e.get("lesson") or "").strip()
        if not lesson:
            continue
        conf = e.get("confidence", 5)
        try:
            conf = max(1, min(10, int(conf)))
        except Exception:
            conf = 5
        await _db_exec(
            "INSERT INTO knowledge_base (kdate,category,lesson,source,confidence,created_at) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(category, lesson) DO NOTHING",
            (kdate, (e.get("category") or "MARKET_BEHAVIOUR").upper()[:40], lesson[:500],
             e.get("source", source), conf, now),
            tag="add_knowledge",
        )


async def get_knowledge(limit: int = 60, category: str | None = None) -> list[dict]:
    if category:
        return await _db_fetchall(
            "SELECT * FROM knowledge_base WHERE category=? ORDER BY confidence DESC, id DESC LIMIT ?",
            (category, int(limit)), tag="get_knowledge",
        )
    return await _db_fetchall(
        "SELECT * FROM knowledge_base ORDER BY confidence DESC, id DESC LIMIT ?",
        (int(limit),), tag="get_knowledge",
    )


# ── AI strategy lab ───────────────────────────────────────────────────────────

async def upsert_ai_strategy(strategy: dict) -> None:
    name = (strategy.get("name") or "").strip()
    if not name:
        return
    rules = strategy.get("rules", [])
    await _db_exec(
        "INSERT INTO ai_strategies (name,created_date,rationale,rules,status,stats,updated_at) "
        "VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(name) DO UPDATE SET rationale=excluded.rationale, rules=excluded.rules, "
        "updated_at=excluded.updated_at",
        (name[:120], strategy.get("created_date") or _now_ist()[:10],
         (strategy.get("rationale") or "")[:800], json.dumps(rules),
         (strategy.get("status") or "PROPOSED").upper(), json.dumps(strategy.get("stats", {})),
         _now_ist()),
        tag="upsert_ai_strategy",
    )


async def update_ai_strategy_status(name: str, status: str) -> None:
    await _db_exec(
        "UPDATE ai_strategies SET status=?, updated_at=? WHERE name=?",
        (status.upper(), _now_ist(), name), tag="update_ai_strategy_status",
    )


async def get_ai_strategies() -> list[dict]:
    rows = await _db_fetchall(
        "SELECT * FROM ai_strategies ORDER BY id DESC LIMIT 100", (), tag="get_ai_strategies"
    )
    for r in rows:
        for k in ("rules", "stats"):
            try:
                r[k] = json.loads(r[k]) if r.get(k) else ([] if k == "rules" else {})
            except Exception:
                pass
    return rows


# ── AI suggestions (feature requests from the brain) ─────────────────────────

async def add_ai_suggestions(sdate: str, suggestions: list[dict]) -> None:
    now = _now_ist()
    for s in suggestions:
        text = (s.get("suggestion") or "").strip()
        if not text:
            continue
        await _db_exec(
            "INSERT INTO ai_suggestions (sdate,category,suggestion,priority,status,created_at) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(suggestion) DO NOTHING",
            (sdate, (s.get("category") or "OTHER").upper()[:30], text[:500],
             (s.get("priority") or "MEDIUM").upper(), "NEW", now),
            tag="add_ai_suggestions",
        )


async def get_ai_suggestions(limit: int = 100) -> list[dict]:
    return await _db_fetchall(
        "SELECT * FROM ai_suggestions ORDER BY "
        "CASE priority WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END, id DESC LIMIT ?",
        (int(limit),), tag="get_ai_suggestions",
    )

