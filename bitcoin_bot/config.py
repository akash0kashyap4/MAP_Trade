import os
from datetime import time
from pytz import timezone

# ======================== EXCHANGE CONFIG ========================
EXCHANGE = {
    "name": "binance",
    "testnet": os.getenv("BINANCE_TESTNET", "False").lower() == "true",
    "api_key": os.getenv("BINANCE_API_KEY", ""),
    "api_secret": os.getenv("BINANCE_API_SECRET", ""),
    "testnet_url": "https://testnet.binance.vision",
    "mainnet_url": "https://api.binance.com",
    "ws_url": "wss://stream.binance.com:9443/ws",
}

# ======================== TRADING CONFIG ========================
TRADING = {
    "pairs": ["BTCUSDT"],  # Trading pairs
    "quote_asset": "USDT",
    "timeframe": "5m",  # 1m, 5m, 15m, 1h, etc
    "decision_interval": 5,  # minutes between Claude decisions
    "base_order_size": 0.01,  # BTC lot size
    "paper_trade": os.getenv("PAPER_TRADE", "True").lower() == "true",
    "max_positions": 2,  # max concurrent positions
    "max_daily_loss_usd": 500,  # hard circuit breaker
    "risk_per_trade_pct": 0.02,  # 2% of capital per trade
}

# ======================== AI / CLAUDE CONFIG ========================
AI = {
    "model": os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"),
    "claude_bin": os.getenv("CLAUDE_BIN", "/usr/local/bin/claude"),
    "timeout_sec": 10,
    "decision_prompt_type": "autonomy",  # autonomy / conservative / aggressive
    "cache_context": True,
}

# ======================== MARKET / HOURS CONFIG ========================
MARKET = {
    "timezone": timezone("UTC"),  # BTC trades 24/7 UTC
    "trading_enabled": True,  # Always true for crypto
    "quiet_hours": [],  # Empty - trade 24/7, no quiet hours
    "pre_market_buffer_min": 0,  # No pre-market in crypto
    "holidays": [],  # Crypto doesn't have holidays (maybe major shutdowns)
}

# ======================== RISK MANAGEMENT ========================
RISK = {
    "max_drawdown_pct": 0.15,  # 15% portfolio drawdown hard-stop
    "position_sizing": "kelly",  # kelly / fixed / exponential
    "kelly_fraction": 0.25,  # Use 25% of Kelly formula
    "max_leverage": 1.0,  # Start without leverage
    "fallback_sl_pct": 0.03,  # 3% SL if AI omits (for safety)
    "fallback_target_pct": 0.06,  # 6% target if AI omits
    "min_confidence": 0.5,  # min confidence to enter trade
}

# ======================== FEES CONFIG ========================
FEES = {
    "maker": 0.001,  # 0.1% Binance maker fee
    "taker": 0.001,  # 0.1% Binance taker fee
    "slippage": 0.003,  # Assume 0.3% slippage on entry
    "withdrawal": 0.0005,  # 0.05% withdrawal fee (if converting to fiat)
}

# ======================== DATA STORAGE ========================
DATA = {
    "db_path": os.getenv("DB_PATH", "bitcoin_bot/data/trading.db"),
    "candle_retention_days": 365,
    "trade_history_retention_days": 1825,  # 5 years
}

# ======================== API / DASHBOARD ========================
API = {
    "host": os.getenv("API_HOST", "0.0.0.0"),
    "port": int(os.getenv("API_PORT", "8000")),
    "reload": os.getenv("RELOAD", "False").lower() == "true",
    "basic_auth_user": os.getenv("BASIC_AUTH_USER", "admin"),
    "basic_auth_pass": os.getenv("BASIC_AUTH_PASS", "password"),
}

# ======================== LOGGING & MONITORING ========================
LOGGING = {
    "level": os.getenv("LOG_LEVEL", "INFO"),
    "file": "bitcoin_bot/logs/trading.log",
    "max_bytes": 10 * 1024 * 1024,  # 10 MB
    "backup_count": 5,
}

# ======================== ALERTS & NOTIFICATIONS ========================
ALERTS = {
    "telegram_enabled": os.getenv("TELEGRAM_ENABLED", "False").lower() == "true",
    "telegram_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
    "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
}

# ======================== BACKTEST CONFIG ========================
BACKTEST = {
    "start_date": "2023-01-01",  # Default backtest range
    "end_date": "2024-12-31",
    "starting_balance": 10000,  # USD
    "strategies": ["claude_driven", "rsi_ema", "macd_cross"],
}
