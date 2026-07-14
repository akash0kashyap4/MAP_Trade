import os
from datetime import date
from dotenv import load_dotenv

load_dotenv()

# Deployment environment: "development" (default) | "production".
# Production tightens security: API docs are disabled and default/weak
# credentials are refused at boot. Set ENV=production in the systemd unit.
ENV = os.getenv("ENV", "development").strip().lower()
IS_PRODUCTION = ENV == "production"

# AI Brain provider: "claude" (paid, default) | "gemini" (Google, free tier).
# Switch with AI_PROVIDER in .env — no code change needed. Gemini's free tier is
# enough to run the bot in paper mode at zero cost; Claude gives more consistent
# decisions for live trading.
AI_PROVIDER = os.getenv("AI_PROVIDER", "claude").strip().lower()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Google Gemini (free tier) — get a key at https://aistudio.google.com/apikey
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

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
    "lots":            1,
    "paper_trade":     True,   # False = live trading via AngelOne
    "max_positions":   2,      # max concurrent live positions (safety)
    "max_daily_loss":  5000,   # hard safety brake — blocks new orders when hit
    # Fallback SL/TP used ONLY if AI omits sl_premium / target_premium.
    "fallback_sl_pct":     0.30,   # 30% below entry
    "fallback_target_pct": 0.60,   # 60% above entry
    "stop_loss_rs":    500,    # fallback for backtests
    "target_rs":       1000,   # fallback for backtests
    "min_confidence":  1,      # kept for schema compat — trust AI's own conf
    "trailing_sl_trigger": 0.40,   # move SL to cost when profit hits 40% of target
    "trailing_sl_step":    0.20,   # trail SL by 20% of premium each step
    
    # Advanced Risk Management Settings (0 / disabled by default for backward compatibility)
    "max_risk_per_trade":        0,     # Max ₹ risk/loss per trade (e.g. 2000)
    "max_trades_per_symbol":     0,     # Max trades per symbol per day (e.g. 3)
    "consecutive_loss_limit":    0,     # Max consecutive losses before cooldown (e.g. 2)
    "cooldown_duration_minutes": 120,   # Loss cooldown duration in minutes
    "session_profit_lock":       0,     # Stop entries if daily P&L >= this (e.g. 8000)
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
DB_PATH = os.getenv("DB_PATH", "trading_bot.db")
