# RAGI — Autonomous Options Trading Bot

Self-learning paper-trading bot for NSE index options (Nifty 50, Bank Nifty, Sensex).
Groww API for market data; **Claude Sonnet 4.6** (via Claude Code CLI or the
aerolink proxy) as the sole decision brain.

> **Full AI autonomy.** There are no hard pre-AI filters (no VIX cap, no IV cap,
> no time-of-day blocks, no min-confidence gate). Claude alone decides entry, stop-loss,
> target, and trailing-SL every tick. The only safety brakes are the ₹5 000 daily-loss
> circuit breaker and "must have enough capital".

---

## Features

- **AI-Powered Decisions** — every 5 min Claude gets full market context (5m + 15m
  structure, S/R, sweeps, phase, option-chain analytics, IV, PCR, VIX, global cues)
  and returns a JSON decision including its own `sl_premium` / `target_premium`.
- **AI-Managed Exits** — while a position is in profit, Claude is polled every 5 min
  to decide `HOLD` / `MOVE_SL` / `EXIT`. No mechanical trailing formula.
- **Realistic Costs** — every fill applies 1.5% slippage; every exit charges
  brokerage + STT + txn + SEBI + stamp + GST so paper P&L matches a real broker.
- **Self-Learning** — nightly at 21:00 IST Claude reviews the last 30 days of
  trades and can suggest rule adjustments (surfaced in the dashboard).
- **Live Feed** — Groww API for indices + option LTPs; REST fallback if feed drops.
- **Global Cues at 08:30** — Dow/Nasdaq/Crude/DXY/India-VIX/prev-close fetched via
  `yfinance` + `curl_cffi` browser impersonation (Yahoo blocks bare AWS IPs).
- **Dashboard** — FastAPI + SSE at `https://akash.mehakva.com` (Basic Auth).
- **Backtest Engine** — 5 built-in strategies plus a Claude-driven mode.

---

## Architecture

```
main.py                  FastAPI app + lifespan startup
├── ai/
│   ├── agent.py         Claude CLI subprocess — trade + trailing + nightly review
│   ├── schema.py        Pydantic validators for every Claude JSON reply
│   ├── learner.py       Nightly self-learning from trade history
│   └── prompts.py       System + user prompts (autonomy mode, no hard rules)
├── bot/
│   ├── trader.py        LiveTrader — market loop, AI-driven entry / trail / exit
│   ├── fees.py          Indian options cost model (brokerage/STT/GST/stamp/slip)
│   ├── decision_log.py  Structured per-tick trail (guard_pass / guard_block / info)
│   ├── risk.py          Position sizing helpers
│   └── strategy.py      Market context builder, 5-min resampler, S/R + sweeps
├── groww/
│   ├── oauth.py         Groww API connection check & Telegram alerts
│   ├── live_feed.py     Live feed + intraday candle refresh + option LTP loop
│   ├── historical.py    Candle fetch, intraday endpoint, option chain analytics
│   ├── quotes.py        REST LTP for indices and open option positions
│   └── auth.py          Groww API client helper
├── indicators/
│   └── calculator.py    RSI, EMA, VWAP/TWAP, Supertrend, Bollinger, ATR
├── data/
│   ├── store.py         In-memory LiveStore (prices, positions, signals)
│   └── database.py      aiosqlite — candles, signals, trades, learning_rules
├── api/
│   ├── routes.py        REST endpoints incl. /groww/health, /_demo/seed
│   └── sse.py           Server-Sent Events for the dashboard
├── backtest/engine.py   Vectorised backtest engine
├── scripts/
│   ├── send_login_link.py   04:00 IST cron — Groww health check
│   └── claude_warmup.py     06:30 IST cron — warms Claude CLI cache
├── scheduler.py         APScheduler — premarket 08:30, ticks, EOD 15:15, learn 21:00
└── dashboard/index.html Single-file terminal dashboard
```

---

## Instruments & Lot Sizes (NSE Jan 2026 revision)

| Index      | Instrument Key            | Lot | Step |
|------------|---------------------------|-----|------|
| Nifty 50   | `NSE_INDEX\|Nifty 50`     | 65  | 50   |
| Bank Nifty | `NSE_INDEX\|Nifty Bank`   | 30  | 50   |
| Sensex     | `BSE_INDEX\|SENSEX`       | 20  | 100  |

---

## Configuration (`config.py`)

Only truly safety-critical knobs remain — everything else is delegated to Claude.

```python
TRADING = {
    "lots":                 1,
    "paper_trade":          True,
    "max_positions":        999,
    "max_daily_loss":       5000,   # hard circuit breaker
    "fallback_sl_pct":      0.30,   # used ONLY if AI omits sl_premium
    "fallback_target_pct":  0.60,   # used ONLY if AI omits target_premium
    "min_confidence":       1,      # schema-compat; AI's conf is trusted
}
```

The NSE 2026 trading-holiday list is baked into `config.NSE_HOLIDAYS` and used by
`is_market_day()` — the bot skips premarket + trading on holidays automatically.

---

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

Key runtime deps: `yfinance>=1.5.1`, `curl_cffi>=0.7.0` (Yahoo needs browser
impersonation on AWS IPs), `pydantic>=2`, `aiosqlite`, `fastapi`, `apscheduler`,
`python-telegram-bot`, `pytz`.

### 2. Configure `.env`
```
GROWW_API_KEY=your_groww_api_key
GROWW_SECRET_KEY=your_groww_secret_key
ANTHROPIC_API_KEY=your_anthropic_key
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
CLAUDE_MODEL=claude-sonnet-4-6
CLAUDE_BIN=/usr/local/bin/claude
```

### 3. Run
```bash
python main.py                # dev
sudo systemctl restart ragi   # on EC2
```

Dashboard: **https://akash.mehakva.com** (Basic Auth: `raj / <password>`).

---

## Decision Flow (every 5 min during market hours)

1. Pull last 60 min of 1-min candles → resample to 5-min (12 bars).
2. Compute RSI, EMA 9/21/50, VWAP, ATR + build price structure
   (5m + 15m swing, BOS, liquidity sweep, opening range, phase).
3. Fetch option-chain analytics (ATM strike, PCR, max pain, ATM IV, OI, days-to-exp).
4. Feed the whole context to Claude via `claude -p ... --model claude-sonnet-4-6`.
5. Validate the JSON reply against `ai/schema.DecisionSchema` (pydantic).
6. If `action ∈ {BUY_CE, BUY_PE}`:
   - Apply 1.5% ask-side slippage to the option LTP.
   - Use AI's `sl_premium` / `target_premium` (fallback 30% / 60%).
   - Enter paper position; subscribe LTP over WS.
7. On every tick, any position in profit is passed to `agent.check_trailing_sl()`
   → Claude decides `HOLD` / `MOVE_SL` / `EXIT`.
8. SL / target / AI-exit hits are logged with realistic P&L
   (raw − brokerage − STT − GST − stamp − slippage).

Every step is captured in a `DecisionLog` and persisted next to the signal so the
dashboard can render the full gate-by-gate reasoning.

---

## Daily Automation (EC2, Ubuntu 24.04)

| Time (IST) | Job                             | Where                             |
|------------|---------------------------------|-----------------------------------|
| 04:00      | Groww API health check          | `ragi-token-refresh.timer`        |
| 06:30      | Claude CLI warm-up ping         | `ragi-claude-warmup.timer`        |
| 08:30      | Premarket analysis + Telegram   | `scheduler.py` inside `ragi.service` |
| 09:15-15:30| 5-min market ticks              | inside `ragi.service`             |
| 15:15      | EOD square-off + Telegram summary| inside `ragi.service`            |
| 21:00      | Nightly self-learning           | inside `ragi.service`             |

Skipped automatically on weekends and the 16 NSE 2026 holidays.

---

## Manual API Endpoints

| Method | Endpoint                       | Description                              |
|--------|--------------------------------|------------------------------------------|
| GET    | `/api/status`                  | Full bot state (prices, positions, ...)  |
| POST   | `/api/tick`                    | Manually trigger one AI decision cycle   |
| GET    | `/api/trades`                  | Trade history                            |
| POST   | `/api/learn/run-now`           | Trigger nightly learning immediately     |
| POST   | `/api/trades/import`           | Import historical trades                 |
| POST   | `/api/backtest/run`            | Run backtest                             |
| GET    | `/api/groww/status`            | Check Groww API connection               |
| GET    | `/api/groww/health`            | Ping Groww API and send Telegram alert   |
| POST   | `/api/_demo/seed`              | Seed dashboard w/ sample data (screenshots)|

---

## Requirements

- Python 3.11+
- Groww account with API access (`GROWW_API_KEY` + `GROWW_SECRET_KEY`)
- Claude Code CLI authenticated **OR** aerolink proxy (`ANTHROPIC_BASE_URL` +
  `ANTHROPIC_API_KEY` in `~/.claude/settings.json`)
- On AWS: `curl_cffi` is required for yfinance to work (Yahoo blocks datacenter IPs)

---

## Notes

- `paper_trade=True` by default — no live orders. Flip in `config.py` once
  strategy is proven.
- Groww API keys are long-lived; rotate them from the Groww developer console if needed.
- The bot uses Claude Code CLI via subprocess — no direct `ANTHROPIC_API_KEY`.
