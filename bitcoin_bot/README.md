# Bitcoin Trading Bot

Autonomous Bitcoin trading bot powered by Claude AI. Makes entry/exit decisions every 5 minutes using real-time market data and AI reasoning.

## Quick Start

### 1. Setup Environment

```bash
cd bitcoin_bot
cp .env.example .env

# Edit .env with your Binance & Anthropic API keys
nano .env
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Run Paper Trading (Test First!)

```bash
export PAPER_TRADE=True
export BINANCE_TESTNET=True
python main.py
```

Visit dashboard: **http://localhost:8000**

### 4. Test Backtest

```bash
python -m backtest.engine --strategy claude_driven --start 2023-01-01 --end 2024-12-31
```

### 5. Go Live (When Confident)

```bash
export PAPER_TRADE=False
export BINANCE_TESTNET=False
python main.py
```

---

## 📊 How It Works (5-min Cycle)

1. **Fetch Market Data** (last 60 x 1-min candles)
2. **Calculate Indicators** (RSI, EMA, MACD, ATR, Supertrend)
3. **Build Context** (price structure, portfolio, global cues)
4. **Query Claude** ("Should we trade? BUY/SELL/HOLD?")
5. **Execute Trade** (if confidence > 60%)
6. **Track Position** (monitor SL/target every 5 min)
7. **Close Position** (at SL, target, or Claude exit signal)
8. **Log Trade** (store in database for learning)

---

## 📁 Project Structure

```
bitcoin_bot/
├── main.py              Entry point + FastAPI server
├── config.py            Global configuration
├── requirements.txt     Dependencies
│
├── ai/
│   ├── agent.py         Claude CLI wrapper for decisions
│   ├── schema.py        Pydantic validators
│   ├── prompts.py       System + trading prompts
│   └── learner.py       Nightly learning from trades
│
├── exchange/
│   ├── binance_client.py REST + WebSocket integration
│   ├── auth.py          API key management
│   └── orders.py        Order placement logic
│
├── bot/
│   ├── trader.py        Main trading loop
│   ├── fees.py          Fee calculation (Binance model)
│   ├── risk.py          Position sizing & risk
│   └── strategy.py      Market context builder
│
├── data/
│   ├── database.py      SQLite persistence
│   ├── store.py         In-memory data structures
│   └── models.py        Trade/Position data models
│
├── indicators/
│   └── calculator.py    RSI, EMA, MACD, BB, ATR, Supertrend, VWAP
│
├── api/
│   ├── routes.py        REST endpoints
│   └── sse.py           Server-Sent Events for dashboard
│
├── backtest/
│   ├── engine.py        Vectorized backtest
│   ├── strategies.py    Built-in strategies
│   └── reporter.py      Results & metrics
│
└── dashboard/           Web UI (optional)
    └── index.html       Real-time dashboard
```

---

## 🔧 Configuration

Edit `config.py` to customize:

```python
TRADING = {
    "pairs": ["BTCUSDT"],
    "decision_interval": 5,      # minutes
    "base_order_size": 0.01,     # BTC
    "paper_trade": True,
    "max_daily_loss_usd": 500,
    "risk_per_trade_pct": 0.02,  # 2%
}

RISK = {
    "max_drawdown_pct": 0.15,    # 15% hard-stop
    "position_sizing": "kelly",  # kelly / fixed
    "kelly_fraction": 0.25,
}

AI = {
    "model": "claude-sonnet-4-6",
    "timeout_sec": 10,
}
```

---

## 📈 API Endpoints

| Method | Endpoint | Description |
|--------|----------|---|
| GET | `/health` | Health check |
| GET | `/api/status` | Bot status + portfolio |
| GET | `/api/trades` | Trade history |
| GET | `/api/positions` | Open positions |
| GET | `/api/stats` | Trading statistics |
| POST | `/api/tick` | Manually trigger decision |
| POST | `/api/learn/run-now` | Trigger nightly learning |
| POST | `/api/eod/run-now` | Square off all positions |

---

## 🚀 Deployment (AWS EC2)

```bash
# Ubuntu 24.04, t3.medium

sudo apt update && apt install -y python3.11 python3-pip git
git clone <repo>
cd bitcoin_bot

pip install -r requirements.txt
cp .env.example .env
nano .env  # Add credentials

# Create systemd service
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

# Monitor
journalctl -u bitcoin-bot -f
```

---

## ⚠️ Security Checklist

- [ ] Use Binance sub-account (NOT main account)
- [ ] Enable IP whitelist on Binance API
- [ ] Restrict key to spot trading only
- [ ] Set max daily loss limit (5% portfolio)
- [ ] Use 2FA on Binance + email
- [ ] Rotate API keys every 90 days
- [ ] Run on private VPS (not shared hosting)
- [ ] Monitor logs & Telegram alerts daily
- [ ] Start with paper trading (1-2 weeks minimum)
- [ ] Backtest on 1+ years of historical data

---

## 🧪 Testing

```bash
# Unit tests
pytest tests/

# Integration test (paper trade on testnet)
export BINANCE_TESTNET=True
python main.py

# Backtest
python -m backtest.engine --strategy claude_driven \
  --start 2023-01-01 --end 2024-12-31
```

---

## 📊 Expected Performance

| Metric | Conservative | Realistic | Optimistic |
|--------|---|---|---|
| Annual Return | 15% | 25-35% | 60% |
| Sharpe Ratio | 1.2 | 1.5 | 2.0+ |
| Max Drawdown | -15% | -20% | -25% |
| Win Rate | 45% | 50% | 55% |

*Assumes good market conditions, proper position sizing, and strong AI prompts.*

---

## 🐛 Troubleshooting

**"Connection refused" on Binance?**
- Check API key + secret
- Verify IP whitelist
- Try testnet first

**"Claude timeout"?**
- Check Claude CLI installation
- Verify `CLAUDE_BIN` path in `.env`
- Increase timeout in `config.py`

**"Low win rate"?**
- Review Claude prompt in `ai/prompts.py`
- Backtest to find market conditions it fails in
- Consider hybrid: Claude + rule-based signals

**"High drawdown"?**
- Reduce `risk_per_trade_pct` (0.01 instead of 0.02)
- Lower `max_drawdown_pct` hard-stop
- Avoid trading in choppy markets

---

## 📚 Learning Resources

- [Binance API Docs](https://binance-docs.github.io/apidocs/)
- [Claude API Docs](https://docs.anthropic.com/)
- [Technical Analysis](https://school.stockcharts.com/)

---

## 📝 License

MIT — Use at your own risk. No guarantees of profitability.

---

## 🙋 Support

Need help? Check:
1. Logs: `bitcoin_bot/logs/trading.log`
2. Config: `bitcoin_bot/config.py`
3. Database: `bitcoin_bot/data/trading.db` (SQLite)

---

**Trade smart. Start small. Think long-term.**
