# MAP TRADE Bot — Changes Context (Antigravity)
> Is session me kiye gaye sabhi changes ka complete summary.
> Branch: `claude/dazzling-bohr-zoc44b`
> Locally apply karne ke liye Step-by-step guide niche hai.

---

## 1. Dashboard URL Change
**File:** `README.md`

Purana URL `https://ragi.rajwork.online` → naya `https://akash.mehakva.com` (teen jagah)

---

## 2. Upstox → Groww (README documentation)
**File:** `README.md`

| Kya badla | Pehle | Ab |
|-----------|-------|----|
| Header description | Upstox v2/v3 API | Groww API |
| Live Feed | Upstox WS v3 | Groww API |
| Architecture tree | `upstox/` folder | `groww/` folder |
| API route | `/upstox/callback` | `/groww/callback` |
| `.env` example | `UPSTOX_*` keys | `GROWW_API_KEY`, `GROWW_SECRET_KEY` |
| Manual endpoints | `/api/upstox/login-link` | `/api/groww/status` |

---

## 3. groww/oauth.py — Pura rewrite
**File:** `groww/oauth.py`

Pehle: Upstox OAuth flow (login URL, code exchange, token write).
Ab: Groww key-based auth — sirf 2 functions:
```python
check_api_connection()  # Groww API live hai ya nahi
send_telegram(text)     # Telegram alert
```
Hata diye: `build_login_url`, `exchange_code_for_token`, `write_token_to_env`

---

## 4. routers/routes.py — Endpoints + Trading Mode API
**File:** `routers/routes.py`

**Upstox → Groww endpoints:**
| Pehle | Ab |
|-------|----|
| `GET /api/upstox/login-link` | `GET /api/groww/status` |
| `GET /api/upstox/callback` | `GET /api/groww/health` |

**Naye endpoints (Live Trading Toggle):**
```
GET  /api/trading/mode          → current mode return karta hai ("paper"/"live")
POST /api/trading/set-mode      → mode switch karta hai
                                  body: {"mode": "paper"} ya {"mode": "live"}
                                  "live" switch karne se pehle AngelOne creds validate karta hai
```

---

## 5. scripts/send_login_link.py — Cron script rewrite
**File:** `scripts/send_login_link.py`

Pehle: Roz 04:00 IST pe Upstox OAuth URL Telegram pe bhejta tha.
Ab: Groww API health check karta hai, status Telegram pe bhejta hai.

---

## 6. AngelOne Live Trading Integration — NEW
**Naye files:**

### `angelone/__init__.py`
Empty init file.

### `angelone/auth.py`
TOTP-based AngelOne login. Session 6 ghante cache hota hai.
```python
get_angel_client() → SmartConnect  # logged-in session return karta hai
get_profile()      → dict           # account info
```
Required env vars: `ANGEL_API_KEY`, `ANGEL_CLIENT_ID`, `ANGEL_PASSWORD`, `ANGEL_TOTP_SECRET`

### `angelone/orders.py`
Order placement wrapper:
```python
find_option_token(index, expiry_ddmmmyyyy, strike, option_type) → (symbol, token)
place_market_order(symbol, token, qty, transaction_type, exchange, product) → order_id
place_limit_order(...)  → order_id
get_order_status(order_id) → {status, fill_price, quantity, message}
cancel_order(order_id) → bool
get_positions() → list
get_funds() → dict
```
Scrip master: AngelOne ka JSON file se option tokens lookup karta hai.

### `bot/order_executor.py`
Async executor with safety checks:

**Safety checks (entry se pehle):**
1. Market hours: 09:15–15:15 IST only
2. Daily loss limit: `max_daily_loss` breach pe block
3. Capital check: available capital >= order cost
4. Max positions: `max_positions` limit enforce

**Methods:**
```python
executor.enter(instrument, strike, option_type, expiry_str, quantity,
               entry_price, sl, target, store, telegram_fn) → position dict | None
executor.exit(position, reason, current_price, telegram_fn) → fill_price
executor.reset_daily_loss()  # roz subah call karo
```
Har order pe Telegram alert bhejta hai (attempt + fill + exit).

---

## 7. bot/trader.py — Live branch update
**File:** `bot/trader.py`

`_executor = OrderExecutor()` session-level instance add kiya.

Live branch (when `TRADING["paper_trade"] = False`):
- Pehle: stub `groww.orders.place_market_order` call tha (broken)
- Ab: `_executor.enter()` via AngelOne, DB me `trade_type="live"` save, fill price confirm karta hai

Exit path:
- `is_live` position pe `_executor.exit()` call karta hai (real SELL order)
- Paper positions: pehle jaisi simulation

---

## 8. dashboard/index.html — Complete UI redesign
**File:** `dashboard/index.html`

**Layout:**
- Left sidebar: navigation (Dashboard, Market Data, Open Positions, Trade Log, Backtest, Reports, Settings) + Market Watch (Nifty/BankNifty/Sensex) + P&L + Capital
- Center: Candlestick chart + Technical Indicators (12 cells with sparklines) + Open Positions table + Today's Trades + Backtest
- Right panel: AI Brain (brain SVG + confidence ring) + Today's Bias + Signal History + Learning

**Key features:**
- `lightweight-charts@4.1.3` (CDN) — real candlestick chart
- Brain SVG — cyan/purple gradient, animated neural dots, glow effect
- Sparklines — SVG polylines for RSI, EMA9/21/50, VWAP, Vol Ratio
- Mode dropdown in header — PAPER MODE / REAL MONEY toggle (confirmation modal before live)
- All SSE/API logic preserved

---

## 9. config.py — AngelOne keys + safety defaults
**File:** `config.py`

```python
# Naye keys add kiye
ANGEL_API_KEY     = os.getenv("ANGEL_API_KEY", "")
ANGEL_CLIENT_ID   = os.getenv("ANGEL_CLIENT_ID", "")
ANGEL_PASSWORD    = os.getenv("ANGEL_PASSWORD", "")
ANGEL_TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET", "")

# max_positions default 999 → 2 (live safety ke liye)
TRADING = {
    "paper_trade":   True,   # False = live trading
    "max_positions": 2,      # live mode me max 2 concurrent positions
    "max_daily_loss": 5000,  # ₹5000 breach pe naye orders block
    ...
}
```

---

## 10. requirements.txt
```
smartapi-python   # AngelOne SmartAPI SDK
pyotp             # TOTP generation for 2FA login
```

---

## Local me apply karne ke steps

### Step 1 — Branch pull karo
```bash
git fetch origin
git checkout claude/dazzling-bohr-zoc44b
git pull origin claude/dazzling-bohr-zoc44b
```

### Step 2 — Dependencies install karo
```bash
pip install -r requirements.txt
# includes: smartapi-python, pyotp, growwapi
```

### Step 3 — `.env` file update karo
```env
# Purane Upstox keys hatao (agar hain):
# UPSTOX_TOKEN=...
# UPSTOX_API_KEY=...
# UPSTOX_API_SECRET=...
# UPSTOX_REDIRECT_URI=...

# Groww keys (pehle se hain to confirm karo):
GROWW_API_KEY=your_groww_api_key
GROWW_SECRET_KEY=your_groww_secret_key

# AngelOne keys (live trading ke liye, abhi paper mode me zaroorat nahi):
ANGEL_API_KEY=your_angel_api_key
ANGEL_CLIENT_ID=your_client_id
ANGEL_PASSWORD=your_mpin
ANGEL_TOTP_SECRET=your_totp_base32_secret

# Baaki keys (unchanged):
ANTHROPIC_API_KEY=your_anthropic_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
```

### Step 4 — Live trading ON karna ho to (baad me jab ready ho)
`config.py` me:
```python
TRADING = {
    "paper_trade": False,   # ye line change karo
    ...
}
```
Ya dashboard header me mode dropdown se "REAL MONEY" select karo (AngelOne creds validate hote hain pehle).

---

## Kya nahi badla (important)
- `groww/auth.py` — unchanged (`GrowwAPI` client same hai)
- `groww/historical.py`, `groww/quotes.py`, `groww/live_feed.py` — unchanged
- `ai/agent.py`, `ai/prompts.py` — unchanged
- `bot/risk.py`, `bot/strategy.py`, `bot/fees.py` — unchanged
- `bot/trader.py` paper branch — unchanged (paper mode bilkul same kaam karta hai)
- Database schema, backtest engine — unchanged
- `config.py` me `UPSTOX_TOKEN` aur `BASE_URL` abhi bhi hain (unused, safe to delete manually)
