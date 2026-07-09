# Ragi Bot — Changes Context
> Ye document un sabhi changes ka summary hai jo is session me kiye gaye hain.
> Inhe locally apply karne ke liye niche diye gaye steps follow karo.

---

## 1. Dashboard URL Change
**File:** `README.md`

Purana URL `https://ragi.rajwork.online` replace hua naye URL se `https://akash.mehakva.com`

Teen jagah change kiya:
- Features section me dashboard URL
- `.env` example me `UPSTOX_REDIRECT_URI` (ab `GROWW` wala section hai)
- Setup section me dashboard link

---

## 2. Upstox → Groww (README documentation)
**File:** `README.md`

| Kya badla | Pehle | Ab |
|-----------|-------|----|
| Header description | Upstox v2/v3 API | Groww API |
| Live Feed feature | Upstox WS v3 | Groww API |
| Architecture tree | `upstox/` folder | `groww/` folder |
| API route mention | `/upstox/callback` | `/groww/callback` |
| `.env` example | `UPSTOX_TOKEN`, `UPSTOX_API_KEY`, `UPSTOX_API_SECRET`, `UPSTOX_REDIRECT_URI` | `GROWW_API_KEY`, `GROWW_SECRET_KEY` |
| Manual API endpoints | `/api/upstox/login-link`, `/api/upstox/callback` | `/api/groww/status`, `/api/groww/health` |
| Requirements | Upstox account | Groww account |
| Notes | Upstox token expiry | Groww API keys info |

---

## 3. groww/oauth.py — Pura rewrite
**File:** `groww/oauth.py`

**Pehle:** Upstox OAuth flow tha — login URL banana, code exchange karna, token `.env` me likhna.

**Ab:** Groww API key-based auth hai — koi OAuth URL nahi, koi callback nahi.

Naya file sirf 2 functions rakhta hai:
```python
check_api_connection()   # Groww API live hai ya nahi
send_telegram(text)      # Telegram alert (waise hi raha)
```

Hata diye gaye:
- `UPSTOX_AUTH_URL`, `UPSTOX_TOKEN_URL` constants
- `build_login_url()` function
- `exchange_code_for_token()` function
- `write_token_to_env()` function

---

## 4. routers/routes.py — Endpoints rename
**File:** `routers/routes.py`

Import line badli:
```python
# Pehle
from groww.oauth import build_login_url, exchange_code_for_token, write_token_to_env, send_telegram

# Ab
from groww.oauth import check_api_connection, send_telegram
```

Endpoints badle:

| Pehle | Ab |
|-------|----|
| `GET /api/upstox/login-link` → Upstox OAuth URL return karta tha | `GET /api/groww/status` → Groww API connection check |
| `GET /api/upstox/callback` → Upstox OAuth code exchange + token save + bot restart | `GET /api/groww/health` → Groww API ping + Telegram alert |

---

## 5. scripts/send_login_link.py — Cron script rewrite
**File:** `scripts/send_login_link.py`

**Pehle:** Roz 04:00 IST pe Upstox OAuth login URL Telegram pe bhejta tha (daily token refresh ke liye).

**Ab:** Roz 04:00 IST pe Groww API health check karta hai aur Telegram pe status send karta hai:
- Connected → "Good morning. Ragi is ready. Groww API: Connected"
- Failed → "WARNING: Groww API connection failed! Check GROWW_API_KEY..."

---

## Local me apply karne ke steps

### Step 1 — `.env` file update karo
```
# Ye lines hatao
UPSTOX_TOKEN=...
UPSTOX_API_KEY=...
UPSTOX_API_SECRET=...
UPSTOX_REDIRECT_URI=...

# Ye lines add karo (pehle se hain to bas confirm karo)
GROWW_API_KEY=your_groww_api_key
GROWW_SECRET_KEY=your_groww_secret_key
ANTHROPIC_API_KEY=your_anthropic_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
```

### Step 2 — config.py check karo
`config.py` me ye line abhi bhi purani hai (code me hai, change nahi ki):
```python
UPSTOX_TOKEN = os.getenv("UPSTOX_TOKEN", "")
BASE_URL = "https://api.upstox.com/v2"
```
Agar Upstox bilkul use nahi kar rahe to inhe hata sakte ho ya ignore karo (unused hain).

### Step 3 — Branch se pull karo
```bash
git fetch origin
git checkout claude/dazzling-bohr-zoc44b
```

### Step 4 — Dependencies install karo
```bash
pip install growwapi  # Groww Python SDK
pip install -r requirements.txt
```

---

## Summary — Kya nahi badla (important)
- `groww/auth.py` — waise hi hai, `GrowwAPI` client sahi kaam karta hai
- `groww/historical.py`, `groww/quotes.py`, `groww/live_feed.py` — unchanged
- `bot/trader.py`, `ai/agent.py`, `ai/prompts.py` — unchanged
- Database, backtest engine, dashboard — unchanged
- `config.py` — Upstox variables abhi bhi hain (unused) — manually clean kar sakte ho
