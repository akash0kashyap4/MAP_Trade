# Claude Code Agent Prompt — Self-Learning Options Trading Bot
# Nifty / BankNifty / Sensex | Upstox API | Claude as AI Brain Agent

---

## ROLE

You are **Claude Code**, an autonomous coding and trading agent. You will:
1. Build this entire system from scratch
2. Act as the **AI brain** inside the running bot — analyzing market data and making decisions
3. Self-learn from trade outcomes nightly
4. Run the full daily schedule autonomously

Do not ask for clarification. Build everything. Where choices exist, pick the most robust option.

---

## UPSTOX ENDPOINTS — EXTRACTED FROM WORKING SCRIPT

Use **exactly** these endpoints. They are proven working.

```python
BASE_URL = "https://api.upstox.com/v2"
HEADERS  = {"Authorization": f"Bearer {UPSTOX_TOKEN}", "Accept": "application/json"}

# 1. INDEX SPOT HISTORICAL CANDLES (1-min)
GET {BASE_URL}/historical-candle/{urllib.parse.quote(instrument_key)}/1minute/{date_str}/{date_str}
# Response: data.candles → list of [timestamp, open, high, low, close, volume, oi]

# 2. EXPIRED EXPIRIES LIST
GET {BASE_URL}/expired-instruments/expiries?instrument_key={urllib.parse.quote(instrument_key)}
# Response: data → list of expiry date strings "YYYY-MM-DD"

# 3. EXPIRED OPTION CONTRACT KEY LOOKUP
GET {BASE_URL}/expired-instruments/option/contract?instrument_key={encoded}&expiry_date={expiry}
# Response: data → list of contracts with strike_price, instrument_type, instrument_key

# 4. EXPIRED OPTION HISTORICAL CANDLES (1-min)
GET {BASE_URL}/expired-instruments/historical-candle/{urllib.parse.quote(expired_key)}/1minute/{date_str}/{date_str}
# Response: data.candles → list of [timestamp, open, high, low, close, volume, oi]

# INSTRUMENT KEYS
NIFTY_KEY    = "NSE_INDEX|Nifty 50"
BANKNIFTY_KEY = "NSE_INDEX|Nifty Bank"
SENSEX_KEY   = "BSE_INDEX|SENSEX"

# CONSTANTS (from working script)
ATM_STEP     = 50       # Nifty/BankNifty rounding
SENSEX_STEP  = 100      # Sensex rounding
LOT_SIZES    = {"NIFTY": 75, "BANKNIFTY": 35, "SENSEX": 20}  # verify current
REQUEST_DELAY = 0.35    # seconds between API calls (rate limit safety)
```

---

## SYSTEM OVERVIEW

```
trading_bot/
├── main.py                    # Entry point + FastAPI app
├── config.py                  # All config + secrets
├── scheduler.py               # APScheduler daily jobs
├── requirements.txt
│
├── upstox/
│   ├── auth.py                # Token management
│   ├── historical.py          # Candle fetching (from working script)
│   ├── options.py             # Expiry lookup + option key lookup
│   ├── live_feed.py           # WebSocket live market feed
│   └── orders.py              # Place/modify/cancel orders (paper mode safe)
│
├── data/
│   ├── database.py            # SQLite async (no setup needed) → upgrade to Postgres later
│   ├── models.py              # All table definitions
│   └── store.py               # In-memory live state (prices, positions, signals)
│
├── indicators/
│   └── calculator.py          # RSI, EMA, VWAP, Supertrend, ATR, OI change
│
├── ai/
│   ├── agent.py               # Claude Code agent — the AI brain
│   ├── prompts.py             # All prompts (pre-market, decision, learning)
│   └── learner.py             # Nightly self-learning loop
│
├── backtest/
│   ├── engine.py              # Core backtest runner (no lookahead)
│   ├── simulator.py           # SL + trailing SL simulation
│   ├── parallel.py            # Run N strategy variants simultaneously
│   └── reporter.py            # Stats + CSV export
│
├── bot/
│   ├── strategy.py            # Entry/exit logic
│   ├── risk.py                # Position sizing, SL calculation
│   └── trader.py              # Live trading loop orchestrator
│
├── api/
│   ├── routes.py              # REST endpoints
│   └── sse.py                 # SSE broadcaster (2-second updates)
│
└── dashboard/
    └── index.html             # Full terminal UI — single file
```

---

## MODULE SPECIFICATIONS

---

### `config.py`

```python
import os
from datetime import date

UPSTOX_TOKEN     = os.getenv("UPSTOX_TOKEN", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

BASE_URL  = "https://api.upstox.com/v2"
ATM_STEP  = 50
SENSEX_STEP = 100

INSTRUMENTS = {
    "NIFTY":     "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "SENSEX":    "BSE_INDEX|SENSEX",
}

LOT_SIZES = {"NIFTY": 75, "BANKNIFTY": 35, "SENSEX": 20}

TRADING = {
    "lots":                  1,
    "min_confidence":        7,        # Claude must return >= this to trade
    "max_positions":         2,
    "stop_loss_rs":          500,
    "target_rs":             1000,
    "trailing_sl_trigger":   0.5,      # Start trailing after 50% of target reached
    "trailing_sl_step":      0.25,     # Trail by 25% of premium
    "paper_trade":           True,     # NEVER touch orders.py when True
}

SCHEDULE = {
    "premarket":   "08:30",
    "market_open": "09:15",
    "market_close":"15:15",
    "eod_review":  "15:30",
    "nightly_learn":"21:00",
}

NSE_HOLIDAYS = {
    date(2025, 2, 26), date(2025, 3, 14), date(2025, 4, 14),
    date(2025, 4, 17), date(2025, 8, 15), date(2025, 10, 2),
    date(2026, 1, 1),  date(2026, 1, 26), date(2026, 3, 3),
    date(2026, 4, 14), date(2026, 5, 1),  date(2026, 5, 24),
}

REQUEST_DELAY = 0.35
DB_PATH = "trading_bot.db"
```

---

### `upstox/historical.py`

Port the **exact working logic** from the provided script. Functions needed:

```python
def get_headers() -> dict:
    # Return auth headers using UPSTOX_TOKEN from config

def get_index_candles(instrument_key: str, date_str: str) -> list:
    # Exact endpoint from working script:
    # GET /historical-candle/{encoded_key}/1minute/{date}/{date}
    # Return list of candles: [timestamp, open, high, low, close, volume, oi]
    # Handle errors gracefully, return []

def get_candles_range(instrument_key: str, start_str: str, end_str: str, interval: str = "1minute") -> list:
    # Loop day by day (API is date-bounded), aggregate all candles
    # Skip non-trading days using is_trading_day()
    # Respect REQUEST_DELAY between calls
    # Return merged sorted list

def get_expired_expiries(instrument_key: str) -> list:
    # GET /expired-instruments/expiries?instrument_key={encoded}
    # Return sorted list of expiry date strings

def get_option_instrument_key(instrument_key: str, expiry: str, strike: int, option_type: str) -> Optional[str]:
    # GET /expired-instruments/option/contract?instrument_key={encoded}&expiry_date={expiry}
    # Match strike_price == strike AND instrument_type == option_type
    # If not found, try ATM_STEP ±1, ±2 adjustments (exact logic from working script)
    # Return instrument_key string or None

def get_option_candles(expired_key: str, date_str: str) -> list:
    # GET /expired-instruments/historical-candle/{encoded}/1minute/{date}/{date}
    # Return candle list

def is_trading_day(d: date) -> bool:
    # weekday < 5 AND not in NSE_HOLIDAYS
```

---

### `upstox/live_feed.py`

```python
# Connect to Upstox WebSocket v2 market data feed
# Endpoint: wss://api.upstox.com/v2/feed/market-data-streamer
# Auth: send access_token in connection
# Subscribe to: NIFTY, BANKNIFTY, SENSEX spot + current expiry ATM ±5 strikes CE+PE
# On each tick: update store.py prices dict
# Batch ticks — push to SSE broadcaster every 2 seconds (not on every tick)
# Auto-reconnect on disconnect with exponential backoff
# Log connection status to store.py feed_status field
```

---

### `data/database.py`

Use **SQLite with aiosqlite** (zero setup, works everywhere). 

```python
# Tables to create on init:

# candles(id, instrument, interval, timestamp, open, high, low, close, volume, oi)
# signals(id, timestamp, instrument, action, strike, expiry, confidence, reason, indicators_json, ai_response_json)
# trades(id, trade_type, instrument, action, strike, expiry, entry_time, entry_price,
#         exit_time, exit_price, exit_reason, quantity, pnl_raw, pnl_final, signal_id)
# learning_rules(id, updated_at, rules_json, win_rate, sharpe, version)
# backtest_runs(id, run_at, config_json, stats_json, total_trades, win_rate, profit_factor, max_drawdown, sharpe)

# All writes async. Provide:
async def insert_candle(...)
async def insert_signal(...)
async def insert_trade(...)
async def get_trades(days=30) -> list
async def get_latest_rules() -> dict
async def save_learning_rules(rules: dict, stats: dict)
async def save_backtest_run(config: dict, stats: dict)
```

---

### `indicators/calculator.py`

```python
import pandas as pd
import pandas_ta as ta

def calculate_all(candles: list) -> dict:
    """
    Input: list of candle arrays [timestamp, open, high, low, close, volume, oi]
    Output: dict of all indicator values (latest values only, not full series)
    
    Calculate:
    - RSI(14)
    - EMA(9), EMA(21), EMA(50)
    - VWAP (session)
    - Supertrend(10, 3)
    - Bollinger Bands(20, 2) → upper, middle, lower
    - ATR(14)
    - Volume ratio (current vs 20-bar avg)
    - OI change % (last candle vs 10 candles ago)
    - Trend direction: 'UP' | 'DOWN' | 'SIDEWAYS' based on EMA alignment
    - Price vs VWAP: 'ABOVE' | 'BELOW'
    - RSI zone: 'OVERBOUGHT' | 'OVERSOLD' | 'NEUTRAL'
    
    CRITICAL: Use only data[:n] for candle n — no lookahead ever.
    Return latest values as flat dict.
    """
```

---

### `ai/agent.py` — THE CLAUDE CODE AI BRAIN

This is the most important module. Claude Code acts as an **agentic loop**, not a single API call.

```python
import anthropic

class TradingAgent:
    """
    Claude Code agent that:
    1. Receives market context
    2. Reasons step-by-step about the trade
    3. Returns structured decision
    4. Logs full reasoning chain
    """
    
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model  = "claude-opus-4-5"   # Use best model for trading decisions
        self.conversation_history = []     # Maintain context across 5-min checks
    
    async def premarket_analysis(self, global_data: dict) -> dict:
        """
        Called at 8:30 AM.
        Feed global market data, get day's trading plan.
        Returns: {bias, key_levels, risk_level, recommended_stance, reasoning}
        """
        # Build prompt from prompts.py
        # Call Claude with extended thinking if needed
        # Return structured dict
    
    async def decide_trade(self, market_context: dict) -> dict:
        """
        Called every 5 minutes during market hours.
        
        market_context includes:
        - instrument: NIFTY / BANKNIFTY / SENSEX
        - spot_price, spot_change_pct
        - last_10_candles (5-min OHLCV)
        - indicators: dict from calculator.py
        - options_snapshot: {pcr, max_pain, atm_iv, oi_buildup}
        - open_positions: list
        - today_pnl: float
        - premarket_bias: dict (from 8:30 AM analysis)
        - time_of_day: "HH:MM"
        - historical_win_rate_similar: float (from learning DB)
        
        Returns:
        {
            "action": "BUY_CE" | "BUY_PE" | "HOLD" | "EXIT_ALL" | "NO_TRADE",
            "instrument": "NIFTY",
            "strike": 24500,
            "expiry": "2025-06-26",
            "confidence": 8,           # 1-10, must be >= TRADING.min_confidence
            "reasoning": "step by step explanation",
            "entry_price_approx": 120,
            "sl_premium": 84,          # 30% below entry
            "target_premium": 240,
            "risk_reward": 2.0
        }
        """
        # Append to conversation_history (maintain intra-day context)
        # Claude sees the full day's context, not just current candle
        # Parse JSON response, validate fields
        # If confidence < min_confidence → force action = "NO_TRADE"
        # Log full prompt + response to DB
    
    async def check_trailing_sl(self, position: dict, current_price: float) -> dict:
        """
        Every 5 min, check if trailing SL should be moved.
        Returns: {action: "HOLD"|"MOVE_SL"|"EXIT", new_sl: float, reason: str}
        """
    
    async def nightly_review(self, trades: list) -> dict:
        """
        Called at 9 PM. Feed 30 days of trades.
        Claude analyzes patterns and returns updated rules.
        Returns: {
            winning_setups: list,
            losing_setups: list,
            time_analysis: dict,
            updated_rules: dict,
            new_confidence_threshold: int,
            notes: str
        }
        """
    
    def reset_daily_context(self):
        """Call at market open. Clear intra-day conversation history."""
        self.conversation_history = []
```

---

### `ai/prompts.py`

Build these exact prompts:

```python
PREMARKET_SYSTEM = """
You are an expert Indian options trader specializing in Nifty, BankNifty, and Sensex.
Your task: analyze pre-market data and create a trading plan for the day.
Be concise. Focus on actionable insights.
Always respond in valid JSON only. No markdown. No explanation outside JSON.
"""

PREMARKET_USER = """
Date: {date}
Time: 08:30 IST

Global Markets:
- SGX Nifty: {sgx_nifty} ({sgx_change}%)
- Dow Futures: {dow_futures} ({dow_change}%)
- Nasdaq Futures: {nasdaq_futures} ({nasdaq_change}%)
- Crude Oil: ${crude} ({crude_change}%)
- Dollar Index: {dxy}
- VIX (India): {india_vix}

Previous Day:
- Nifty Close: {prev_nifty}
- BankNifty Close: {prev_banknifty}
- PCR (Nifty): {prev_pcr}

Analyze and return JSON:
{
  "bias": "BULLISH" | "BEARISH" | "NEUTRAL",
  "bias_strength": 1-10,
  "key_support": [levels],
  "key_resistance": [levels],
  "risk_level": "LOW" | "MEDIUM" | "HIGH",
  "recommended_stance": "AGGRESSIVE" | "CONSERVATIVE" | "AVOID",
  "focus_instruments": ["NIFTY", "BANKNIFTY"],
  "avoid_times": ["09:15-09:30"],
  "reasoning": "2-3 sentences"
}
"""

DECISION_SYSTEM = """
You are an autonomous options trading agent for Indian markets.
You analyze 5-minute candle data and decide whether to trade.
You have full context of today's market behavior.
Be decisive. Either trade with conviction or skip.
Always respond in valid JSON only. No markdown, no preamble.
"""

DECISION_USER = """
Time: {time} IST | Date: {date}

INSTRUMENT: {instrument} | Spot: {spot_price} ({spot_change_pct:+.2f}%)

Today's Bias (from 8:30 AM analysis):
{premarket_bias}

Last 10 Five-Min Candles (oldest first):
{candles_table}

Technical Indicators:
- RSI(14): {rsi}
- EMA: 9={ema9} 21={ema21} 50={ema50}
- VWAP: {vwap} (price is {price_vs_vwap})
- Supertrend: {supertrend_direction}
- ATR: {atr}
- Trend: {trend}

Options Data:
- ATM Strike: {atm_strike}
- PCR: {pcr}
- Max Pain: {max_pain}
- ATM IV: {atm_iv}%
- OI Buildup: {oi_buildup}

Current Positions: {open_positions}
Today's P&L: ₹{today_pnl:,}
Historical Win Rate (similar setup): {win_rate_similar}%

Decide and return JSON:
{
  "action": "BUY_CE" | "BUY_PE" | "HOLD" | "EXIT_ALL" | "NO_TRADE",
  "instrument": "NIFTY" | "BANKNIFTY" | "SENSEX",
  "strike": <integer or null>,
  "expiry": "YYYY-MM-DD or null",
  "confidence": <1-10>,
  "reasoning": "<step by step, max 100 words>",
  "entry_price_approx": <float or null>,
  "sl_premium": <float or null>,
  "target_premium": <float or null>,
  "risk_reward": <float or null>
}
"""

TRAILING_SL_USER = """
Position: {instrument} {strike}{option_type}
Entry Premium: ₹{entry}
Current Premium: ₹{current}
Current SL: ₹{current_sl}
P&L: ₹{pnl} ({pnl_pct:+.1f}%)
Time: {time}

Should SL be moved? Return JSON:
{
  "action": "HOLD" | "MOVE_SL" | "EXIT",
  "new_sl": <float or null>,
  "reason": "<one sentence>"
}
"""

NIGHTLY_REVIEW_SYSTEM = """
You are a trading strategy analyst. Review trade history and identify patterns.
Update the trading rules based on what worked and what didn't.
Return only valid JSON.
"""

NIGHTLY_REVIEW_USER = """
Review last {days} days of trades:

{trades_table}

Summary Stats:
- Total: {total} | Wins: {wins} | Losses: {losses}
- Win Rate: {win_rate:.1f}%
- Total P&L: ₹{total_pnl:,}

Analyze and return updated rules JSON:
{
  "winning_setups": ["describe top 3"],
  "losing_setups": ["describe top 3"],
  "best_time_windows": ["HH:MM-HH:MM"],
  "avoid_time_windows": ["HH:MM-HH:MM"],
  "best_market_conditions": ["describe"],
  "updated_confidence_threshold": <6-9>,
  "position_sizing_note": "<one sentence>",
  "key_insight": "<most important finding>",
  "rule_changes": {"param": "new_value"}
}
"""
```

---

### `backtest/engine.py`

**Port and extend the working script logic.** Key differences from the working script:

1. Add AI brain decisions (Claude) instead of simple green/red candle logic
2. Add multi-instrument support (Nifty + BankNifty + Sensex)
3. Add parallel variant testing
4. Store results to DB

```python
class BacktestEngine:
    
    def __init__(self, use_ai_brain: bool = False):
        self.use_ai_brain = use_ai_brain
        # If False: use simple rule-based logic (fast, no API cost)
        # If True: call Claude for each decision (slow, costs money, more realistic)
    
    def run(self, instrument: str, start_str: str, end_str: str, config: dict) -> BacktestResult:
        """
        For each trading day in range:
          1. Fetch spot candles (using exact endpoint from working script)
          2. Find ATM strike from 9:15 candle
          3. Determine signal (green → PE, red → CE) OR use AI brain
          4. Find nearest expiry using get_expired_expiries()
          5. Get option instrument key using get_option_instrument_key()
          6. Fetch option 9:16 candle
          7. Simulate trade with SL + trailing SL via simulator.py
          8. Log to DB
        
        CRITICAL: No lookahead. Indicators use only past data.
        Return BacktestResult with full stats.
        """
    
    def run_parallel_variants(self, base_config: dict, param_grid: dict, n_jobs: int = 4):
        """
        Run multiple config combinations in parallel using multiprocessing.
        
        param_grid example:
        {
            "min_confidence": [6, 7, 8],
            "sl_percentage": [20, 30, 40],
            "entry_time_filter": ["09:20", "09:25", "09:30"]
        }
        
        Generates all combinations, runs each as separate backtest.
        Returns ranked DataFrame sorted by Sharpe ratio.
        Print progress table as results come in.
        """

class BacktestResult:
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    raw_pnl: float
    sl_hits: int
    tgt_hits: int
    profit_factor: float
    sharpe_ratio: float
    max_drawdown: float
    max_drawdown_pct: float
    best_day: tuple
    worst_day: tuple
    win_rate_by_hour: dict
    win_rate_by_day_of_week: dict
    trades: list
    
    def print_report(self):
        # Match the colorama-based report style from working script
        # Add extra stats not in original
    
    def to_csv(self, filename: str):
        # Save all trades to CSV
```

---

### `backtest/simulator.py`

```python
def simulate_trade(
    entry_price: float,
    candles_after_entry: list,
    sl_rs: float,
    target_rs: float,
    lot_size: int,
    lots: int,
    trailing_sl_trigger: float = 0.5,
    trailing_sl_step: float = 0.25,
) -> TradeResult:
    """
    Simulate order from entry through subsequent candles.
    
    Logic (from working script, enhanced):
    - Entry: next candle open after signal (+ 0.5% slippage)
    - Each subsequent candle:
      * Check if candle low <= SL → SL hit (conservative: assume SL hit before target)
      * Check if candle high >= target → Target hit
      * Update trailing SL if profit > trailing_sl_trigger * target
    - Exit at 3:15 PM candle close if neither hit
    - Apply brokerage: ₹20/side + STT (0.05% on sell side)
    
    Returns TradeResult with entry, exit, pnl, exit_reason
    """
```

---

### `api/sse.py`

```python
# FastAPI SSE endpoint: GET /stream
# Every 2 seconds, yield this JSON structure:

SSE_PAYLOAD = {
    "ts":        "2025-06-17T10:32:45+05:30",
    "prices": {
        "NIFTY":     {"ltp": 24500.50, "chg": 45.0,  "chg_pct": 0.18},
        "BANKNIFTY": {"ltp": 52300.00, "chg": -120.0, "chg_pct": -0.23},
        "SENSEX":    {"ltp": 80500.00, "chg": 234.0,  "chg_pct": 0.29},
    },
    "positions": [
        {"instrument": "NIFTY", "strike": 24500, "type": "CE",
         "entry": 120.0, "ltp": 145.0, "pnl": 1875.0, "sl": 84.0}
    ],
    "signals": [
        {"time": "10:30", "instrument": "BANKNIFTY", 
         "action": "BUY_PE", "confidence": 8, "reason": "..."}
    ],
    "pnl": {"realized": 2500, "unrealized": 1875, "total": 4375},
    "ai_status": "analyzing" | "waiting" | "in_trade" | "learning",
    "feed_status": "live" | "reconnecting" | "closed",
    "today_bias": "BULLISH",
    "next_check": "10:35",
}

# Implementation:
# - Use asyncio.Queue for pushing updates from live_feed.py
# - SSE response with Content-Type: text/event-stream
# - Heartbeat every 30 seconds to keep connection alive
# - Handle client disconnect cleanly
```

---

### `dashboard/index.html`

**Apply frontend-design skill fully.**

**Aesthetic Direction:** Industrial trading terminal. Think: what a serious quant trader would want staring at them for 6 hours a day. NOT corporate SaaS. NOT generic dark mode.

- Background: `#050508` near-black
- Grid lines: `#1a1a2e` subtle blue-black
- Primary data: `#e8e8e0` off-white (easy on eyes)
- Positive/Buy: `#00ff88` electric green
- Negative/Sell: `#ff3355` sharp red  
- Warning/Neutral: `#ffaa00` amber
- Live indicator: `#00d4ff` cyan
- Font: `IBM Plex Mono` (Google Fonts) for all data, `Barlow Condensed` for labels/headers

**Layout — CSS Grid full viewport:**
```
┌─────────────────────────────────────────────────────────────────────┐
│ HEADER: Bot name | Date/Time IST | Feed status dot | AI status      │
├──────────────┬──────────────────────────────┬───────────────────────┤
│ LEFT (20%)   │ CENTER (50%)                 │ RIGHT (30%)           │
│              │                              │                       │
│ NIFTY        │ 5-MIN CANDLE TABLE           │ AI DECISION FEED      │
│ ltp chg      │ time|o|h|l|c|vol|rsi|trend  │ confidence arc        │
│              │                              │ latest reasoning      │
│ BANKNIFTY    │ ────────────────────         │ ─────────────────     │
│ ltp chg      │ INDICATOR PANEL              │ SIGNAL HISTORY        │
│              │ RSI VWAP EMA Supertrend      │ scrollable feed       │
│ SENSEX       │                              │                       │
│ ltp chg      │ ────────────────────         │ ─────────────────     │
│              │ POSITIONS TABLE              │ LEARNING PANEL        │
│ ──────────── │ entry|current|pnl|sl         │ win rate              │
│ TODAY P&L    │                              │ last update           │
│ ₹XXXX        │ ────────────────────         │ active rules          │
│              │ BACKTEST CONTROLS            │                       │
│ POSITIONS    │ [Run Backtest] progress      │                       │
│ count        │ results table                │                       │
└──────────────┴──────────────────────────────┴───────────────────────┘
│ BOTTOM STRIP: Live trade log — auto-scroll — new entries flash in   │
└─────────────────────────────────────────────────────────────────────┘
```

**JavaScript requirements:**
```javascript
// SSE Connection
const es = new EventSource('/stream');
es.onmessage = (e) => {
    const data = JSON.parse(e.data);
    updatePrices(data.prices);      // Flash cells on change direction
    updatePositions(data.positions); // Update P&L in real time
    updateSignals(data.signals);    // New signals slide in from top
    updateAIStatus(data.ai_status); // Pulsing status indicator
    updatePnL(data.pnl);           // Animated counter
};

// Price cells: flash green border on uptick, red on downtick, fade after 1s
// Confidence: animated SVG arc, 0-10 scale, color changes at thresholds
// Trade log: new entries prepend with slide-down animation
// Feed status: pulsing dot (cyan=live, red=disconnected, amber=reconnecting)
// All timestamps in IST

// Backtest panel:
// [Run Backtest] button → POST /backtest/run with config
// Show progress via polling GET /backtest/status
// Render results table sorted by sharpe ratio
```

---

### `scheduler.py`

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

IST = pytz.timezone("Asia/Kolkata")

def setup_scheduler(trader, agent, learner):
    sched = AsyncIOScheduler(timezone=IST)
    
    # Pre-market: fetch global data + AI day plan
    sched.add_job(trader.premarket_analysis, "cron", hour=8, minute=30)
    
    # Market loop: every 5 min from 9:15 to 15:15
    sched.add_job(trader.market_loop_tick, "cron",
                  day_of_week="mon-fri",
                  hour="9-15", minute="15,20,25,30,35,40,45,50,55",
                  # Also run at :00 for hours 10-15
                  )
    # Simpler: use interval trigger starting at 9:15
    
    # EOD: close all positions
    sched.add_job(trader.end_of_day, "cron", hour=15, minute=15)
    
    # Nightly learning
    sched.add_job(learner.run_nightly_review, "cron", hour=21, minute=0)
    
    # Weekly deep review (Sunday 10 AM)
    sched.add_job(learner.weekly_review, "cron", day_of_week="sun", hour=10)
    
    return sched
```

---

### `bot/trader.py`

```python
class LiveTrader:
    
    def __init__(self, agent: TradingAgent, store, db):
        self.agent = agent
        self.store = store
        self.db    = db
        self._market_open = False
    
    async def premarket_analysis(self):
        """8:30 AM: Fetch global data, get AI day plan, store in store.py"""
        global_data = await fetch_global_cues()   # yfinance: ^NSEBANK, SGX, Dow futures
        plan = await self.agent.premarket_analysis(global_data)
        self.store.premarket_bias = plan
        await send_telegram(f"📊 Day Plan: {plan['bias']} | Risk: {plan['risk_level']}")
    
    async def market_loop_tick(self):
        """Every 5 min: get data → AI decision → act"""
        if not self._market_open:
            return
        
        for instrument in ["NIFTY", "BANKNIFTY", "SENSEX"]:
            context = await self.build_market_context(instrument)
            decision = await self.agent.decide_trade(context)
            
            await self.db.insert_signal(decision)
            
            if decision["action"] in ["BUY_CE", "BUY_PE"]:
                if decision["confidence"] >= TRADING["min_confidence"]:
                    await self.execute_trade(decision)
            
            elif decision["action"] == "EXIT_ALL":
                await self.exit_all_positions(instrument)
        
        # Check trailing SL on open positions
        for position in self.store.positions:
            sl_decision = await self.agent.check_trailing_sl(
                position, self.store.prices[position["instrument"]]["ltp"]
            )
            if sl_decision["action"] == "MOVE_SL":
                await self.update_sl(position, sl_decision["new_sl"])
            elif sl_decision["action"] == "EXIT":
                await self.exit_position(position, reason="ai_exit")
    
    async def execute_trade(self, decision: dict):
        if TRADING["paper_trade"]:
            # Log to DB as paper trade, update store.positions
            # NEVER call orders.py
            pass
        else:
            # Call orders.py to place real order
            pass
    
    async def end_of_day(self):
        """3:15 PM: Close all, send summary, reset"""
        await self.exit_all_positions()
        summary = self.store.get_daily_summary()
        await send_telegram(f"📈 EOD: {summary}")
        self.store.reset_daily()
        self.agent.reset_daily_context()
        self._market_open = False
```

---

### `ai/learner.py`

```python
class Learner:
    
    async def run_nightly_review(self):
        """9 PM: Feed 30 days of trades to Claude, get updated rules"""
        trades = await db.get_trades(days=30)
        if len(trades) < 10:
            return   # Not enough data yet
        
        rules = await agent.nightly_review(trades)
        stats = calculate_stats(trades)
        
        await db.save_learning_rules(rules, stats)
        
        # Update live config from AI recommendations
        if rules.get("updated_confidence_threshold"):
            TRADING["min_confidence"] = rules["updated_confidence_threshold"]
        
        await send_telegram(
            f"🧠 Nightly Learn: WR={stats['win_rate']:.1f}% "
            f"Insight: {rules['key_insight']}"
        )
    
    async def weekly_review(self):
        """Sunday: Deeper analysis, update backtest assumptions"""
        trades = await db.get_trades(days=90)
        # Run backtest with current rules vs previous rules
        # Compare performance
        # Send detailed Telegram report
```

---

## DATABASE — SQLite (aiosqlite)

```python
# Use aiosqlite for async SQLite. No Postgres setup needed.
# On first run: create all tables automatically.
# Upgrade path: same schema works on Postgres with asyncpg later.

import aiosqlite

DB_PATH = "trading_bot.db"

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
    indicators TEXT,      -- JSON
    ai_response TEXT      -- full JSON response
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
    signal_id INTEGER REFERENCES signals(id)
);

CREATE TABLE IF NOT EXISTS learning_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    updated_at TEXT NOT NULL,
    rules TEXT NOT NULL,    -- JSON
    win_rate REAL,
    sharpe REAL,
    version INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    config TEXT,            -- JSON
    stats TEXT,             -- JSON
    total_trades INTEGER,
    win_rate REAL,
    profit_factor REAL,
    max_drawdown REAL,
    sharpe REAL
);
"""
```

---

## REQUIREMENTS.TXT

```
fastapi==0.111.0
uvicorn[standard]==0.30.0
anthropic==0.28.0
apscheduler==3.10.4
pandas==2.2.0
pandas-ta==0.3.14b
yfinance==0.2.40
aiosqlite==0.20.0
requests==2.31.0
aiohttp==3.9.5
numpy==1.26.4
scipy==1.13.0
colorama==0.4.6
python-telegram-bot==21.3
websockets==12.0
python-dotenv==1.0.1
pytz==2024.1
```

No `upstox-python-sdk` — use raw `requests` calls matching the working script exactly.

---

## CRITICAL RULES FOR CLAUDE CODE

1. **Port the working script endpoints exactly.** Do not guess URLs. Use what's proven.
2. **No lookahead in backtest.** At candle N, only use candles 0..N-1 for indicators.
3. **Paper trade flag is sacred.** When `TRADING["paper_trade"] = True`, never touch `orders.py`.
4. **Claude is the brain.** Every trade decision routes through `ai/agent.py`. The simple green/red logic from the working script is only the fallback when `use_ai_brain=False`.
5. **All times in IST.** `pytz.timezone("Asia/Kolkata")` everywhere.
6. **SQLite first.** aiosqlite, no setup, works out of the box.
7. **REQUEST_DELAY = 0.35** between all Upstox API calls. The working script proved this is needed.
8. **Handle missing data gracefully.** If any API call fails, skip that day/candle (exact pattern from working script).
9. **No stubs. No TODOs. No `pass`.** Every function must be fully implemented.
10. **Frontend-design skill applied to dashboard.** IBM Plex Mono + Barlow Condensed. Industrial terminal aesthetic. 2-second SSE updates. Every price cell flashes on tick direction.

---

## BUILD ORDER

Build in this exact sequence. Test each before proceeding:

```
1. config.py + requirements.txt
2. data/database.py (SQLite, create all tables, test init)
3. upstox/historical.py (port from working script, verify candle fetch)
4. indicators/calculator.py (verify RSI/EMA/VWAP on test data)
5. backtest/simulator.py (test SL + trailing SL logic)
6. backtest/engine.py (rule-based first, no AI, verify with known dates)
7. ai/prompts.py + ai/agent.py (test Claude decision on sample data)
8. backtest/engine.py (add AI brain mode)
9. backtest/parallel.py + backtest/reporter.py
10. data/store.py + upstox/live_feed.py
11. bot/strategy.py + bot/trader.py
12. ai/learner.py
13. api/routes.py + api/sse.py + main.py
14. dashboard/index.html (full terminal UI, SSE connected)
15. scheduler.py
16. upstox/orders.py (last — paper mode only until verified)
```

---

## START COMMANDS

```bash
# Setup
pip install -r requirements.txt

# Set environment variables
export UPSTOX_TOKEN="your_token"
export ANTHROPIC_API_KEY="your_key"
export TELEGRAM_BOT_TOKEN="optional"
export TELEGRAM_CHAT_ID="optional"

# Initialize DB
python -c "import asyncio; from data.database import init_db; asyncio.run(init_db())"

# Run backtest (rule-based, no AI cost)
python -c "
from backtest.engine import BacktestEngine
e = BacktestEngine(use_ai_brain=False)
result = e.run('NIFTY', '2025-01-01', '2025-05-30', {})
result.print_report()
result.to_csv('backtest_results.csv')
"

# Run parallel variants
python -c "
from backtest.parallel import run_variants
results = run_variants('NIFTY', '2025-01-01', '2025-05-30', n_jobs=4)
print(results.head(10))
"

# Start full system (dashboard at http://localhost:8000)
uvicorn main:app --host 0.0.0.0 --port 8000
```

---

## FIRST RUN CHECKLIST (Claude Code should verify each)

- [ ] DB initializes with all 5 tables
- [ ] `get_index_candles("NSE_INDEX|Nifty 50", "2025-05-30")` returns candle list
- [ ] `get_expired_expiries("NSE_INDEX|Nifty 50")` returns sorted expiry list
- [ ] `get_option_instrument_key(...)` returns a valid key string
- [ ] `get_option_candles(key, "2025-05-30")` returns option candles
- [ ] `calculate_all(candles)` returns dict with RSI, EMA, VWAP populated
- [ ] Backtest runs for at least 1 day without error
- [ ] Claude agent returns valid JSON decision
- [ ] SSE endpoint streams data at `/stream`
- [ ] Dashboard loads at `http://localhost:8000` and connects to SSE
