# RAGI BOT — working notes for Claude

## Standing instruction: review the AI brain's report section on every audit/change

Whenever you **audit the repo or change anything**, also review these two parts
of the dashboard's **Reports** section, because the self-learning brain surfaces
real bugs and needs there — don't rely only on the code:

1. **KNOWLEDGE BASE** — lessons the brain has learned, tagged `MISTAKE` /
   `RISK` / `MARKET_BEHAVIOUR`. A `MISTAKE` entry is usually a real defect
   (e.g. "premarket plan and news analysis both failed to execute before market
   open with no alert raised").
2. **AI REQUESTS** — features/data/tools the brain says it needs, tagged
   `HIGH` / `MEDIUM` and `TOOL` / `DATA` / `SIGNAL`. Treat `HIGH` items as
   actionable work, not backlog.

If you can reach the running bot, read them via the API/DB; otherwise ask the
operator for the current entries (they can screenshot the tabs). Map each open
item to a concrete code change and address the `MISTAKE`s and `HIGH` requests
before calling an audit done.

### Status of items seen on 2026-07-15

| Source | Item | Status |
|--------|------|--------|
| KB · MISTAKE | Premarket plan + news analysis failed silently, no alert | ✅ Fixed — see below |
| KB · RISK | Default to no-trade when bias/news unavailable | ✅ Correct behavior; now also alerts |
| AI REQ · HIGH/TOOL | Auto health-check/alert if premarket/news job fails by market open | ✅ Implemented |
| AI REQ · MEDIUM/DATA | Sector/index breadth (NIFTY vs BANKNIFTY vs SENSEX, adv/decline) | ⏳ Open follow-up |
| AI REQ · MEDIUM/SIGNAL | Lightweight fallback intraday bias (ORB / VWAP) when pipeline down | ✅ Implemented — `bot/fallback_bias.py` |

## Premarket pipeline health check (implemented)

- `trader.premarket_analysis` (scheduled 08:30) now records health in the store
  (`premarket_status` = pending/ok/failed, `premarket_ran_at`, `premarket_error`)
  and, on failure, raises an **immediate** Telegram alert instead of failing
  silently.
- `trader.pipeline_health_check` (scheduled **09:16**, just after the 09:15
  open) verifies the premarket plan actually produced a bias today; if not it
  alerts once/day. This is the AI brain's HIGH-priority request.
- `GET /api/health/pipeline` exposes the same state for the dashboard.
- Health fields reset in `store.reset_daily()`.

## Fallback intraday bias (implemented)

- `bot/fallback_bias.py::compute_fallback_bias(candles)` derives a bias purely
  from intraday candles: Opening-Range Breakout (first 15 min) + VWAP position.
  Always `risk_level="HIGH"`, `source="fallback_orb_vwap"`.
- `trader._ensure_fallback_bias()` (called each tick) populates
  `store.premarket_bias` with it **only while `premarket_status != "ok"`** — it
  never overrides a real premarket bias and never flips status to "ok", so the
  health alert still fires. This turns a pipeline outage into a genuine (if
  low-confidence) read instead of a blank no-trade.
- Tests: `tests/test_fallback_bias.py`.

## Environment note

This repo's runtime deps (`fastapi`, `dotenv`, `yfinance`, `typer`) are **not**
installed in the Claude web/CI sandbox, so `main.py`, the live trader, and the
Groww data path cannot be executed here — only `py_compile` + the offline Bhav
test suite run. Live smoke tests must be done in the deployed environment.

## Bhav backtest engine

See `AUDIT_REPORT.md` for the 2026-07-15 audit of the Bhav→Groww migration and
`STRATEGY_TEMPLATE.md` for the real strategy API (`ctx.spot()`,
`ctx.buy_option(...)`, `ctx.close_all()` — there is no `bar_index`/`entry_call`).
