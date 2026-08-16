import os
from datetime import date
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Deployment target: "vps" (default) | "android" (Termux on mobile device).
DEPLOYMENT_TARGET = os.getenv("DEPLOYMENT_TARGET", "vps").strip().lower()
IS_ANDROID = DEPLOYMENT_TARGET == "android"

# Deployment environment: "development" (default) | "production".
# Production tightens security: API docs are disabled and default/weak
# credentials are refused at boot. Set ENV=production in the systemd unit.
ENV = os.getenv("ENV", "development").strip().lower()
IS_PRODUCTION = ENV == "production"

# AI Brain provider — "claude" (Anthropic API), "claude_code" (CLI), "copilot"
# (Copilot CLI), "ollama" (local), or a comma-separated fallback chain, e.g.
# "claude_code,copilot,claude". Switch with AI_PROVIDER in .env — no code change.
AI_PROVIDER = os.getenv("AI_PROVIDER", "claude").strip().lower()

# Configurable directories for portable deployment
_REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(_REPO_ROOT / "data_store")))
LOG_DIR = Path(os.getenv("LOG_DIR", str(_REPO_ROOT / "logs")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# Groww Auth
GROWW_API_KEY      = os.getenv("GROWW_API_KEY", "")
GROWW_SECRET_KEY   = os.getenv("GROWW_SECRET_KEY", "")

# AngelOne SmartAPI (live trading)
ANGEL_API_KEY      = os.getenv("ANGEL_API_KEY", "")
ANGEL_CLIENT_ID    = os.getenv("ANGEL_CLIENT_ID", "")
ANGEL_PASSWORD     = os.getenv("ANGEL_PASSWORD", "")
ANGEL_TOTP_SECRET  = os.getenv("ANGEL_TOTP_SECRET", "")


ATM_STEP    = 50
SENSEX_STEP = 100

INSTRUMENTS = {
    "NIFTY":     "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "SENSEX":    "BSE_INDEX|SENSEX",
}

LOT_SIZES = {"NIFTY": 65, "BANKNIFTY": 30, "SENSEX": 20}

INITIAL_CAPITAL = 100_000   # ₹1 lakh dummy capital

TRADING = {
    "lots":            1,      # base lot multiplier; AI can up-size (see size_scaling)
    "paper_trade":     True,   # False = live trading via AngelOne
    "max_positions":   3,      # max concurrent live positions (safety) — was 2
    "max_daily_loss":  5000,   # hard safety brake — only real hard block
    # Fallback SL/TP used ONLY if AI omits sl_premium / target_premium.
    "fallback_sl_pct":     0.30,
    "fallback_target_pct": 0.60,
    "stop_loss_rs":    500,    # fallback for backtests
    "target_rs":       1000,   # fallback for backtests
    "min_confidence":  1,      # trust AI's own conf; may be overridden by learner
    "trailing_sl_trigger": 0.40,
    "trailing_sl_step":    0.20,

    # ─── Risk management (softened so bot actually trades) ───────────────
    "max_risk_per_trade":        2500,   # Max ₹ risk per trade (resizes qty, doesn't block)
    "max_trades_per_symbol":     5,      # was 3 — allow more re-entries per index
    "consecutive_loss_limit":    3,      # was 2
    "cooldown_duration_minutes": 60,     # was 120 — halved so bot resumes faster
    # Session profit lock: does NOT block entries anymore — it tightens all
    # open positions' SL to breakeven so gains are protected while the bot
    # can keep hunting new setups.
    "session_profit_lock":       8000,

    # ─── Confidence-based position sizing ────────────────────────────────
    # AI confidence -> lot multiplier. High conviction gets scaled up.
    # 1-6 = 1×, 7-8 = 2×, 9-10 = 3×. Set to None to disable.
    "size_scaling": {6: 1, 8: 2, 10: 3},

    # ─── Partial booking (needs qty >= 2*lot to fire) ────────────────────
    # When ltp reaches entry + partial_book_ratio * (target - entry), book half
    # the position and move SL to breakeven. Rest rides for full target.
    "partial_book_enabled": True,
    "partial_book_ratio":   0.60,   # book half at 60% of the way to target
}

SCHEDULE = {
    "premarket":    "08:30",
    "market_open":  "09:15",
    "market_close": "15:15",
    "eod_review":   "15:30",
    "nightly_learn":"21:00",
}

NSE_HOLIDAYS = {
    # 2024
    date(2024, 1, 22), date(2024, 3, 25), date(2024, 3, 29),
    date(2024, 4, 14), date(2024, 4, 17), date(2024, 5, 23),
    date(2024, 6, 17), date(2024, 7, 17), date(2024, 8, 15),
    date(2024, 10, 2), date(2024, 10, 24), date(2024, 11, 15),
    date(2024, 12, 25),
    # 2025
    date(2025, 2, 26), date(2025, 3, 14), date(2025, 4, 14),
    date(2025, 4, 17), date(2025, 8, 15), date(2025, 10, 2),
    # 2026 - official NSE circular (16 trading holidays)
    date(2026, 1, 15),   # Municipal Corporation Election - Maharashtra (Thu)
    date(2026, 1, 26),   # Republic Day (Mon)
    date(2026, 3, 3),    # Holi (Tue)
    date(2026, 3, 26),   # Shri Ram Navami (Thu)
    date(2026, 3, 31),   # Shri Mahavir Jayanti (Tue)
    date(2026, 4, 3),    # Good Friday (Fri)
    date(2026, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti (Tue)
    date(2026, 5, 1),    # Maharashtra Day (Fri)
    date(2026, 5, 28),   # Bakri Id (Thu)
    date(2026, 6, 26),   # Muharram (Fri)
    date(2026, 9, 14),   # Ganesh Chaturthi (Mon)
    date(2026, 10, 2),   # Mahatma Gandhi Jayanti (Fri)
    date(2026, 10, 20),  # Dussehra (Tue)
    date(2026, 11, 10),  # Diwali-Balipratipada (Tue) - muhurat trading separate
    date(2026, 11, 24),  # Prakash Gurpurb Sri Guru Nanak Dev (Tue)
    date(2026, 12, 25),  # Christmas (Fri)
}


def is_market_day(d: date | None = None) -> bool:
    """True only on NSE trading days (weekday + not on holiday list)."""
    from datetime import datetime
    import pytz
    if d is None:
        d = datetime.now(pytz.timezone("Asia/Kolkata")).date()
    return d.weekday() < 5 and d not in NSE_HOLIDAYS

REQUEST_DELAY = 0.35
DB_PATH = os.getenv("DB_PATH", str(DATA_DIR / "trading_bot.db"))

# Web server binding — configurable for Android (direct access) vs VPS (behind nginx)
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))

# Trading mode safety: default to paper trading. Live requires explicit config.
TRADING_MODE = os.getenv("TRADING_MODE", "paper").strip().lower()
if TRADING_MODE == "live":
    TRADING["paper_trade"] = False
