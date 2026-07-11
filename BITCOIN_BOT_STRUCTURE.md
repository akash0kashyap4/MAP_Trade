# Bitcoin Trading Bot — Architecture & Structure

## 📊 Project Overview

Autonomous Bitcoin trading bot using **Claude AI** as the decision brain.
- **Exchange:** Binance Spot & Futures
- **Trading Pairs:** BTC/USDT, BTC/USDC
- **Decision Frequency:** Every 5-60 min (configurable)
- **AI Brain:** Claude Sonnet/Opus via Claude Code CLI
- **Capital Management:** Automated position sizing + risk limits

---

## 📁 Project Structure

```
bitcoin_bot/
├── main.py                      FastAPI app + lifespan startup
├── config.py                    Global config (exchange, models, limits)
├── requirements.txt             Dependencies
├── .env                         API keys & credentials
│
├── ai/
│   ├── __init__.py
│   ├── agent.py                 Claude CLI subprocess integration
│   ├── schema.py                Pydantic validators for Claude responses
│   ├── prompts.py               System & user prompts (autonomy rules)
│   └── learner.py               Nightly self-learning from trades
│
├── exchange/
│   ├── __init__.py
│   ├── binance_client.py        Binance API wrapper (REST + WebSocket)
│   ├── auth.py                  API key management & auth
│   ├── orders.py                Order placement & management
│   ├── positions.py             Position tracking & updates
│   └── market_data.py           Real-time candles & ticker data
│
├── bot/
│   ├── __init__.py
│   ├── trader.py                Main trading loop (entry/exit logic)
│   ├── fees.py                  Crypto trading costs (Binance fee model)
│   ├── decision_log.py          Structured logging per trade decision
│   ├── risk.py                  Position sizing & risk rules
│   └── strategy.py              Market context builder (RSI, EMA, structure)
│
├── data/
│   ├── __init__.py
│   ├── store.py                 In-memory LiveStore (prices, positions)
│   ├── database.py              SQLite - candles, trades, learning_rules
│   └── models.py                Data models for trades, positions, signals
│
├── indicators/
│   ├── __init__.py
│   └── calculator.py            RSI, EMA, MACD, Bollinger, ATR, Supertrend
│
├── api/
│   ├── __init__.py
│   ├── routes.py                REST endpoints (/status, /tick, /trades, etc)
│   └── sse.py                   Server-Sent Events for dashboard
│
├── backtest/
│   ├── __init__.py
│   ├── engine.py                Vectorized backtest engine
│   ├── strategies.py            Built-in strategy templates
│   └── reporter.py              Backtest results & metrics
│
├── scheduler.py                 APScheduler - market ticks, EOD, learning
├── dashboard/
│   ├── index.html               Web dashboard (single-file, responsive)
│   └── styles.css               Dashboard styling
│
├── scripts/
│   ├── seed_data.py             Generate mock data for testing
│   ├── fetch_historical.py      Download historical candles
│   └── manual_trade.py          CLI for manual trading
│
├── tests/
│   ├── test_agent.py
│   ├── test_trader.py
│   ├── test_indicators.py
│   └── test_exchange.py
│
└── logs/                        Application logs
    └── trading.log
```

---

## 🔄 How It Will Run (High-Level Flow)

### **1. Startup (Boot Phase)**
```
main.py startup
  ↓
Load config (exchange keys, trading params)
  ↓
Connect to Binance (REST + WebSocket)
  ↓
Initialize database (candles, trades, rules)
  ↓
Start scheduler (market ticks, EOD, learning)
  ↓
Launch FastAPI server + SSE feed for dashboard
```

### **2. Trading Cycle (Every 5-60 minutes)**

```
┌─────────────────────────────────────────────┐
│         Market Tick Triggered                │
└────────────┬────────────────────────────────┘
             ↓
    ┌────────────────────────┐
    │ Fetch Market Data      │
    │ • Last 1-min candles   │
    │ • Order book           │
    │ • RSI, EMA, MACD       │
    │ • Volume + volatility  │
    └────────────┬───────────┘
             ↓
    ┌────────────────────────────────────────┐
    │ Build Trading Context (JSON)           │
    │ • 5m structure (highs, lows, closes)   │
    │ • Support & Resistance                 │
    │ • Current portfolio (positions, cash)  │
    │ • Global signals (BTC dominance, etc)  │
    └────────────┬───────────────────────────┘
             ↓
    ┌────────────────────────────────────────┐
    │ Claude AI Decision (subprocess)        │
    │ Prompt: "You are a Bitcoin trader...   │
    │   Given this context, should we trade?"│
    └────────────┬───────────────────────────┘
             ↓
    ┌────────────────────────────────────────┐
    │ Validate Claude's JSON Response        │
    │ • Action: BUY_MARKET / SELL / HOLD     │
    │ • Entry price, SL, target              │
    │ • Confidence score                     │
    └────────────┬───────────────────────────┘
             ↓
         YES? ↓ NO?
         │    └──→ Log decision, skip, continue
         ↓
    ┌────────────────────────────────────────┐
    │ Place Order via Binance                │
    │ • Calculate position size (Kelly/Exp)  │
    │ • Apply realistic slippage (0.1-0.3%)  │
    │ • Submit market order                  │
    └────────────┬───────────────────────────┘
             ↓
    ┌────────────────────────────────────────┐
    │ Track Position in Real-Time            │
    │ Every 5-min: Check SL / Target / Exit  │
    │ Claude polls: "HOLD / MOVE_SL / EXIT?" │
    └────────────┬───────────────────────────┘
             ↓
    ┌────────────────────────────────────────┐
    │ Close Position                         │
    │ • Exit at SL / target / Claude exit    │
    │ • Log realistic P&L (fees included)    │
    │ • Store in database for learning       │
    └────────────┬───────────────────────────┘
             ↓
    ┌────────────────────────────────────────┐
    │ Update Dashboard (SSE event)           │
    │ • New trade added                      │
    │ • Portfolio value updated              │
    │ • Equity curve refreshed               │
    └─────────────────────────────────────────┘
```

### **3. Nightly Learning (21:00 UTC)**
```
Fetch last 30 days of trades
  ↓
Analyze win/loss ratio, drawdown, sharpe
  ↓
Claude reviews patterns (via learner.py)
  ↓
Claude suggests rule adjustments
  ↓
Store suggested rules in database
  ↓
Display in dashboard for approval
```

---

## ✅ PROS — Why Bitcoin Bot is Better Than Stock Bot

| Feature | Stock Bot (Ragi) | Bitcoin Bot | Advantage |
|---------|---|---|---|
| **Trading Hours** | 9:15–15:30 IST (6.25h) | 24/7/365 | 4x more opportunity; global market |
| **Volatility** | ~1-3% daily (indices) | ~2-5% daily (Bitcoin) | Higher rewards if strategy works |
| **Leverage** | No leverage (NSE limitation) | 1-20x futures available | Risk/reward scaling |
| **Fees** | ~0.5-1% (brokerage+tax) | 0.1% (Binance taker fee) | 5-10x lower costs |
| **API Quality** | Groww (limited) | Binance (industry-std) | More data, better stability |
| **Regulatory** | Complex (STT, GST) | Simpler (no STT/GST in crypto) | Cleaner P&L calculation |
| **Global Context** | Only India-focused | BTC sees all global flows | Better signals |
| **AI Training** | Limited (6.25h history) | Rich 24/7 patterns | Claude learns better |

---

## ⚠️ CONS — Challenges of Bitcoin Bot

| Challenge | Details | Mitigation |
|---|---|---|
| **Extreme Volatility** | BTC swings 5-10% on news overnight | Smaller position size (1-2% risk/trade) |
| **Execution Risk** | Exchange outages, network delays | Timeout + fallback order replay |
| **Slippage** | On large market orders, 0.5-1% slip | Start small; use limit orders |
| **AI Latency** | Claude API call might take 2-5 sec | Pre-fetch market data in background |
| **Pump & Dump Risk** | Low liquidity alts; whales manipulate | Only trade BTC/USDT (highest liquidity) |
| **Regulatory Risk** | Some countries restrict crypto trading | Use VPN/proxy or Binance US |
| **Drawdown Severity** | 30-40% drawdown possible in crypto | Hard stop-loss at 5-10% portfolio loss |
| **API Key Safety** | Crypto theft is instant & permanent | Use sub-accounts, IP whitelist, 2FA |
| **Market Hours** | No pre-market or scheduled close events | Adapt AI prompts for 24/7 continuous trading |

---

## 🛠️ Tech Stack

### **Core**
- Python 3.11+
- FastAPI (REST API + dashboard)
- SQLite (trade history + rules database)

### **Exchange Integration**
- `python-binance` (Binance REST + WebSocket)
- `websocket-client` (real-time tickers)

### **Market Data**
- Binance Spot + Futures candles
- `yfinance` (optional: global macro data)
- TradingView signals (optional)

### **AI & Decision**
- Claude Code CLI (subprocess for decisions)
- Pydantic (schema validation)

### **Technical Analysis**
- `ta-lib` or `pandas-ta` (indicators)
- NumPy (backtest calculations)

### **Scheduling & Async**
- APScheduler (market ticks, EOD, learning)
- asyncio (concurrent API calls)

### **Testing & Monitoring**
- pytest (unit + integration tests)
- Telegram alerts (trade notifications)
- SSE (live dashboard feed)

---

## 📋 Configuration (`config.py`)

```python
# Exchange
EXCHANGE = {
    "name": "binance",
    "testnet": False,  # Set True to test first
    "api_key": os.getenv("BINANCE_API_KEY"),
    "api_secret": os.getenv("BINANCE_API_SECRET"),
}

# Trading
TRADING = {
    "pairs": ["BTCUSDT"],
    "quote_asset": "USDT",
    "timeframe": "5m",  # 5-min candles
    "decision_interval": 5,  # minutes
    "lots": 0.01,  # 0.01 BTC = ~600 USD (at 60k BTC)
    "paper_trade": True,  # True = paper, False = live
    "max_positions": 2,
    "max_daily_loss": 500,  # USD hard stop
    "risk_per_trade": 0.02,  # 2% of capital
}

# AI
AI = {
    "model": "claude-sonnet-4-6",
    "claude_bin": "/usr/local/bin/claude",
    "timeout_sec": 10,  # max time for Claude decision
}

# Market Hours (UTC)
MARKET = {
    "trading_enabled": True,  # 24/7
    "quiet_hours": [],  # None - trade 24/7
}

# Risk
RISK = {
    "max_drawdown_pct": 0.15,  # 15% portfolio drawdown hard-stop
    "position_size_method": "kelly",  # kelly / fixed / exponential
    "kelly_fraction": 0.25,  # use 25% of Kelly formula
    "max_leverage": 1.0,  # Start without leverage
}
```

---

## 🚀 Setup & Run

### **1. Clone & Setup**
```bash
git clone https://github.com/akash0kashyap4/ragi_bot.git
cd ragi_bot/bitcoin_bot
pip install -r requirements.txt
```

### **2. Configure `.env`**
```
# Binance
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret

# Claude
ANTHROPIC_API_KEY=your_anthropic_key
CLAUDE_BIN=/usr/local/bin/claude

# Telegram (optional alerts)
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

### **3. Backtest First (NO RISK)**
```bash
python -m backtest.engine --strategy claude_driven --start 2024-01-01 --end 2024-12-31
# Output: Sharpe, Win%, Max-Drawdown, Total Return
```

### **4. Paper Trade (Test on Binance Testnet)**
```bash
# Set EXCHANGE.testnet = True in config.py
python main.py
# Access dashboard: http://localhost:8000
```

### **5. Go Live (WHEN CONFIDENT)**
```bash
# Set TRADING.paper_trade = False, EXCHANGE.testnet = False
# Deploy to AWS EC2 with systemd service
sudo systemctl start bitcoin-bot
```

---

## 📈 Expected Returns & Risks

| Metric | Conservative | Optimistic | Realistic* |
|--------|---|---|---|
| **Annual Return** | 15% | 60% | 25-35% |
| **Sharpe Ratio** | 1.2 | 2.0+ | 1.5 |
| **Max Drawdown** | -15% | -25% | -20% |
| **Win Rate** | 45% | 55% | 50% |
| **Avg Profit/Win** | +2% | +3.5% | +2.5% |
| **Avg Loss/Loss** | -1.5% | -2% | -1.8% |

*Realistic = After fees, slippage, AI latency, market conditions

---

## 🔐 Security Checklist

- [ ] Use Binance sub-account (not main account)
- [ ] Enable IP whitelist on Binance
- [ ] Use read-only API key for market data
- [ ] Restrict trading key to spot trading only
- [ ] Rotate API keys every 90 days
- [ ] Log all trades + decisions (immutable)
- [ ] Set hard portfolio loss limit (5% max drawdown)
- [ ] Run on private VPS (not shared hosting)
- [ ] Use 2FA on Binance + email
- [ ] Monitor Telegram alerts daily

---

## 📊 Dashboard Features

- **Live Trading Ticker** — BTC price, bid/ask, volume
- **Position Panel** — Entry, SL, target, current P&L, trades active
- **Trade History** — Last 30 trades with Claude decision logs
- **P&L Curve** — Equity curve + drawdown chart
- **Daily Stats** — Trades today, win%, sharpe, realized/unrealized
- **Learning Rules** — Suggested rule changes from nightly learner
- **Alerts** — Telegram + in-app notifications for fills, SL hits, errors

---

## 🧪 Testing Strategy

```
Unit Tests (pytest)
├── test_indicators.py      RSI/EMA calculations
├── test_agent.py           Claude prompt → response validation
├── test_trader.py          Entry/exit logic
├── test_fees.py            Fee calculations vs Binance
└── test_exchange.py        Order placement mock

Integration Tests
├── Backtest engine vs live prices
├── Claude API integration
├── Binance order flow
└── Database persistence

Manual Tests
├── Paper trade on testnet (1 week)
├── Check P&L vs Binance
├── Telegram alert delivery
└── Dashboard real-time updates
```

---

## 📱 Deployment (AWS EC2)

```bash
# Ubuntu 24.04, t3.medium (2 vCPU, 4GB RAM)
sudo apt update && apt install python3.11 python3-pip
pip install -r requirements.txt

# Systemd service
sudo tee /etc/systemd/system/bitcoin-bot.service > /dev/null <<EOF
[Unit]
Description=Bitcoin Trading Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/bitcoin_bot
ExecStart=/usr/bin/python3 main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable bitcoin-bot
sudo systemctl start bitcoin-bot
```

---

## 🎯 Next Steps

1. **Create repo structure** ✅ (this doc)
2. **Build exchange client** (Binance wrapper)
3. **Implement trading loop** (entry/exit logic)
4. **Integrate Claude AI** (decision agent)
5. **Build dashboard** (FastAPI + SSE)
6. **Backtest on historical data** (2023-2024)
7. **Paper trade on testnet** (1-2 weeks)
8. **Go live on mainnet** (with hard stops)

---

## Questions?

- **"Will it work?"** → Depends on market conditions + AI prompt quality. Backtest first.
- **"How much capital?"** → Start with $500-$1000. Risk 1-2% per trade.
- **"Is crypto legal?"** → Check your country. Use VPN if needed.
- **"Overnight gaps?"** → BTC doesn't gap like stocks; SL orders usually fill.
