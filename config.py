import os
from datetime import date
from dotenv import load_dotenv

load_dotenv()

UPSTOX_TOKEN      = os.getenv("UPSTOX_TOKEN", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# Groww Auth
GROWW_API_KEY      = os.getenv("GROWW_API_KEY", "")
GROWW_SECRET_KEY   = os.getenv("GROWW_SECRET_KEY", "")

BASE_URL    = "https://api.upstox.com/v2"
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
    "paper_trade":     True,
    "max_positions":   999,
    "max_daily_loss":  5000,   # hard safety brake only — AI decides everything else
    # Fallback SL/TP used ONLY if AI omits sl_premium / target_premium.
    "fallback_sl_pct":     0.30,   # 30% below entry
    "fallback_target_pct": 0.60,   # 60% above entry
    "stop_loss_rs":    500,    # fallback for backtests
    "target_rs":       1000,   # fallback for backtests
    "min_confidence":  1,      # kept for schema compat — trust AI's own conf
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
DB_PATH = "trading_bot.db"
