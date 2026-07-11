"""
SQLite Database for persistent storage
Trades, candles, learning rules, signals
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json

logger = logging.getLogger(__name__)


class Database:
    """SQLite database wrapper"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = None

    async def init(self):
        """Initialize database and create tables"""
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            self.cursor = self.conn.cursor()

            # Create tables
            self._create_tables()
            self.conn.commit()
            logger.info(f"✓ Database initialized: {self.db_path}")

        except Exception as e:
            logger.error(f"Database init error: {e}")
            raise

    def _create_tables(self):
        """Create all necessary tables"""

        # Trades table
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                pair TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL,
                quantity REAL NOT NULL,
                stop_loss REAL,
                target REAL,
                pnl REAL,
                pnl_pct REAL,
                fees REAL,
                status TEXT,
                claude_decision TEXT,
                exit_reason TEXT
            )
        """
        )

        # Candles table (for backtesting)
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS candles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                pair TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                UNIQUE(timestamp, pair)
            )
        """
        )

        # Learning rules table
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                suggestion TEXT,
                priority TEXT,
                applied BOOLEAN DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        # Daily stats table
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                trades_count INTEGER,
                win_count INTEGER,
                loss_count INTEGER,
                win_pct REAL,
                total_pnl REAL,
                max_drawdown REAL,
                sharpe_ratio REAL
            )
        """
        )

    async def log_trade(self, trade: Dict):
        """Store completed trade"""
        try:
            self.cursor.execute(
                """
                INSERT INTO trades (
                    timestamp, pair, side, entry_price, exit_price,
                    quantity, stop_loss, target, pnl, pnl_pct,
                    fees, status, claude_decision, exit_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    datetime.utcnow().isoformat(),
                    trade.get("pair"),
                    trade.get("side"),
                    trade.get("entry_price"),
                    trade.get("exit_price"),
                    trade.get("quantity"),
                    trade.get("stop_loss"),
                    trade.get("target"),
                    trade.get("pnl"),
                    trade.get("pnl_pct"),
                    trade.get("fees"),
                    trade.get("status"),
                    json.dumps(trade.get("claude_decision", {})),
                    trade.get("exit_reason"),
                ),
            )
            self.conn.commit()
            logger.debug(f"✓ Trade logged: {trade}")

        except Exception as e:
            logger.error(f"Trade logging error: {e}")

    async def get_trades_since(self, days: int = 30) -> List[Dict]:
        """Get trades from last N days"""
        try:
            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

            self.cursor.execute(
                "SELECT * FROM trades WHERE timestamp > ? ORDER BY timestamp DESC",
                (cutoff,),
            )
            rows = self.cursor.fetchall()

            return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"Get trades error: {e}")
            return []

    async def get_daily_stats(self) -> Dict:
        """Calculate today's trading stats"""
        try:
            today = datetime.utcnow().date().isoformat()

            # Get today's trades
            self.cursor.execute(
                "SELECT * FROM trades WHERE DATE(timestamp) = ?",
                (today,),
            )
            trades = self.cursor.fetchall()

            if not trades:
                return {
                    "date": today,
                    "trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "win_pct": 0,
                    "pnl": 0,
                }

            total_pnl = sum(float(t["pnl"] or 0) for t in trades)
            wins = sum(1 for t in trades if t["pnl"] and t["pnl"] > 0)
            losses = sum(1 for t in trades if t["pnl"] and t["pnl"] < 0)
            total = len(trades)

            return {
                "date": today,
                "trades": total,
                "wins": wins,
                "losses": losses,
                "win_pct": (wins / total * 100) if total > 0 else 0,
                "pnl": total_pnl,
            }

        except Exception as e:
            logger.error(f"Daily stats error: {e}")
            return {}

    async def store_learning_suggestions(self, suggestions: List[str]):
        """Store nightly learning suggestions"""
        try:
            date = datetime.utcnow().isoformat()

            for i, suggestion in enumerate(suggestions):
                priority = "high" if i == 0 else "medium"
                self.cursor.execute(
                    """
                    INSERT INTO learning_rules (date, suggestion, priority)
                    VALUES (?, ?, ?)
                """,
                    (date, suggestion, priority),
                )
            self.conn.commit()
            logger.debug(f"✓ Stored {len(suggestions)} learning suggestions")

        except Exception as e:
            logger.error(f"Store suggestions error: {e}")

    async def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("Database closed")
