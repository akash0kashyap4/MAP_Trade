# MAP TRADE — Quality Scorecard

Living scorecard driven by the "MAP TRADE → 10/10" review loop. One
high-leverage change per iteration; each pass ships working code + tests +
docs, re-scores the touched category against the rubric, and records it here.

**Overall: 8.0 / 10** _(was 7.5)_

| Category | Score | Δ | Declared ceiling |
|---|---|---|---|
| Architecture | 8.5/10 | — | — |
| Code quality | 8/10 | — | — |
| Testing | 7/10 | — | — |
| Security | 8/10 | — | — |
| Trading logic | 6.5/10 | — | — |
| UI/Dashboards | 8.5/10 | — | — |
| Deployment/Ops | 7.5/10 | — | — |
| **Data reliability** | **9/10** | **+3.5** | **9 — see note** |

---

## Iteration log

### Iteration 1 — Data reliability 5.5 → 9
**Date:** 2026-08-16 · **Category:** Data reliability

**Why this was the highest-leverage pick:** lowest score (5.5) and the single
biggest live-P&L risk. The whole data layer was unofficial NSE/Groww scraping
with a mock generator as last resort, and each fallback set a scattered
`using_mock_*` flag *silently* — so the system could serve mock/stale data while
the dashboard still showed a green "live" badge. That is exactly the failure the
rubric calls out.

**What shipped:**
- `data/health.py` — a dependency-free, clock/alert-injectable data-layer
  circuit breaker. Per-source rolling failure counts; a source trips OPEN after
  3 consecutive failures and closes on the next success. The layer is DEGRADED
  when any critical source (`feed`, `groww_chain`, `groww_options`, `nse_chain`)
  is open OR when mock data is being served.
- **Honest state, single alert.** One Telegram alert fires on the
  healthy→degraded transition and one on recovery — never per-tick spam. Wired
  in `main.py` to the synchronous `send_telegram` (data path runs in executor
  threads).
- **No more silent mock.** `groww/historical.py` and `groww/live_feed.py`
  record success/failure at every fallback branch and flag `set_serving_mock`
  when dropping to the mock generator. `store.sse_payload()` now carries a
  `data_health` block; the AI dashboard shows a loud red "DATA DEGRADED — prices
  are NOT live" banner and flips the feed health dot to red.
- **Operator/probe endpoint:** `GET /api/data/health` returns the full circuit
  snapshot (open sources, per-source counters, serving_mock, status).
- **Tests:** `tests/test_data_health.py` — 11 tests covering trip/close
  thresholds, single-alert-per-transition, alert-sink exceptions not crashing
  the data path, serving-mock degradation, partial-vs-full recovery, and the
  rubric's headline scenario (NSE + Groww both down → degraded + alerted +
  not-live).

**Verification:** full suite `244 passed`; `ruff check` clean. Acceptance check
`test_nse_and_groww_both_down_degrades_and_alerts` passes. (Also updated two
pre-existing `test_risk.py` tests to match the intentional earlier design
change where the session profit-lock stopped blocking entries and the max-
positions cap moved 2→3 — those were stale literals, not regressions.)

**New score: 9/10.** Circuit breaker + transition alerting + honest degraded
state + full fallback-branch test coverage meet all of the rubric's 10-bar
except one clause.

**Declared ceiling — 9/10:** the rubric's 10 bar requires "at least one
official/paid data source as primary or hot-fallback (not scraping-on-
scraping)." That needs a paid market-data subscription (e.g. an official broker
market-data plan), which is a commercial/procurement decision outside this
codebase's control. Everything achievable in code — circuit breaker, alerting,
degrade-don't-lie, token-refresh-on-401 (already in the NSE client) — is done.
Raising to 10 is unblocked the moment a paid feed key is provided; the health
layer already models sources generically, so adding one is a small adapter.

**Still open in this category (for the 10):** integrate a licensed data feed as
a hot-fallback source and register it as a circuit in `data/health.py`.

---

## Open issues (next passes, roughly highest-leverage first)

1. **Trading logic (6.5):** multi-leg spread execution is defined in the
   strategy catalogue but not executed; naked buys aren't gated behind an
   EV-positive filter; no hard confidence/VIX/liquidity gate beyond the daily
   circuit breaker. Removing the "no spreads" ceiling is the biggest remaining
   P&L lever.
2. **Testing (7):** no per-module coverage gate on `bot/` and `ai/`; add a
   coverage threshold in CI and property/fuzz tests on order-sizing & fee math.
3. **Security (8):** add `pip-audit` vuln-scan job to CI; document secret
   rotation.
4. **Code quality (8):** add a type checker (mypy/pyright) to CI.
5. **Deployment/Ops (7.5):** automated DB backup **restore** drill + documented
   RTO. (Likely a declared ceiling below 10 — true HA needs multi-host infra
   out of scope for a single-user system.)
6. **UI/Dashboards (8.5):** formal a11y pass (keyboard nav, contrast, empty/
   error/loading states audited).
7. **Architecture (8.5):** module interface docs + a dependency-graph diagram;
   assert no direct external I/O outside the adapter layers.
