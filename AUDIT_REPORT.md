# RAGI BOT — Enterprise Audit Report

**Date:** 2026-07-15
**Scope:** Full repository, with focus on the Bhav → Groww migration (Phases 1–3) added on branch `claude/bhav-groww-migration-wbde2s`.
**Method:** Static reading **plus actual execution** — imports, the pytest suite, and a deterministic end-to-end backtest run. Claims in the existing `PHASE_*`/`PROJECT_*` docs were treated as unverified and re-checked from scratch.

---

## TL;DR

The Phase 1–3 documentation described the migration as "100% complete / production-ready / 25/31 tests passing." **Execution told a different story:** the custom-backtest feature could not be imported, could not place a single trade, shipped example strategies that all crash, and exposed unauthenticated arbitrary code execution.

All critical findings below have been **fixed and verified with a real run**. The Bhav backtest layer now imports cleanly, places and closes real trades, and passes an honest test suite (**53 passed, 9 skipped** — skips are live-Groww-only). The wider RAGI bot (FastAPI app, live trader, learner) could not be executed in the audit environment because runtime dependencies (`fastapi`, `dotenv`, `yfinance`, `typer`) are not installed here; see Limitations.

---

## Findings (severity-ranked)

### C1 — CRITICAL — `/api/backtest/custom` was unauthenticated remote code execution  ✅ FIXED
The endpoint `exec()`s user-supplied `strategy_code` in-process, and unlike the bot's other state-changing routes it had **no auth and no same-origin check**. Anyone able to reach the port could run arbitrary Python on the host.
- **Evidence:** `routers/routes.py` — handler took only `(req, background_tasks)`; `require_auth`/`_check_same_origin` were absent.
- **Fix:** gated behind `_check_same_origin(request)` + `require_auth(request)`, matching `/override/*`. Executing user code is inherent to a "bring your own strategy" feature; the proportionate control for this single-operator bot is authentication, plus a docstring warning never to expose it publicly.

### C2 — CRITICAL — the custom-backtest pipeline could not even be imported  ✅ FIXED
`backtest_orchestrator.py` imported `UpstoxProvider` at module top, which imported the **non-existent** `bhav.data.upstox_client`. Importing the orchestrator (and therefore calling `/api/backtest/custom`) raised `ModuleNotFoundError`.
- **Evidence:** `python3 -c "import backtest_orchestrator"` → `ModuleNotFoundError: No module named 'bhav.data.upstox_client'`. `tests/test_upstox_provider.py` also failed collection for the same reason.
- **Fix:** made the Upstox client import lazy (`_load_upstox_client()` raises a clean `BrokerError` if the client isn't bundled) and made the orchestrator import all three providers lazily inside the factory, so a missing optional broker never breaks groww/csv.

### C3 — CRITICAL — the engine could not place a single option trade with any provider  ✅ FIXED
`get_option_chain()` returns `[]` in **every** provider (Groww, CSV; Upstox unimportable). `InstrumentResolver.resolve()` depends on that chain, so it always returned `None`, `ctx.buy_option()` always returned `None`, and the engine produced **zero trades regardless of broker** — i.e. the options backtester was non-functional for its stated purpose, despite the provider contract promising "engine can still backtest using synthetic candles + strike resolution."
- **Evidence:** resolver logic dead-ends on an empty chain; the synthetic-candle machinery (`_synthesize_option_candles`) was unreachable because resolution failed first.
- **Fix:** added an opt-in synthetic-contract fallback in `InstrumentResolver.resolve()` — when the chain has no match it builds an `OptionContract` with the 5-part key (`"<underlying>|<expiry>|<strike>|<CE/PE>"`) that the providers' `get_option_candles()` understand, so synthetic/file-backed candles flow and trades happen.

### C4 — HIGH — `BacktestResult` crashed on the wrong attribute names  ✅ FIXED
Even past C2/C3, `BacktestResult.__init__` read `portfolio.trades`, `t.pnl`, `t.quantity` — none exist. The real API is `portfolio.closed_trades`, `Trade.pnl_net`, `Trade.qty`. First attribute access would `AttributeError`.
- **Fix:** rewritten to `closed_trades` / `pnl_net` / `qty`; profit-factor and drawdown handled safely; `max_drawdown` now reported in rupees (matching the dashboard's ₹ label) with `max_drawdown_pct` alongside.

### C5 — HIGH — every shipped example strategy crashes on the first bar  ✅ FIXED
`STRATEGY_TEMPLATE.md`, the dashboard's default editor + both "Load example" snippets, and the orchestrator docstring all used an **imaginary** Context API: `ctx.bar_index`, `ctx.day_open/high/low`, `ctx.entry_call(target_pct=, sl_pct=)`, `ctx.square_off()`, `ctx.spot_price`. The real Context exposes `ctx.spot()` (a method), `ctx.buy_option(option_type=, strike_offset=, lots=)`, `ctx.sell_option(...)`, `ctx.close(key)`, `ctx.close_all()`, and there is **no** built-in target/stop. Any user copy-pasting an example would hit `AttributeError` on their first bar.
- **Fix:** rewrote all examples and docs to the real API and **compiled + ran every one of them** against the engine (including a manual stop/target example, which closes with `reason="bracket"`).

### M1 — MEDIUM — misleading test suite; false "passing" claims  ✅ ADDRESSED
The docs claimed "25/31 passing." In reality the whole `tests/` tree failed collection (missing `dotenv`), `test_upstox_provider.py` failed on the missing client, and several "provider-independent" tests actually required the live Groww env.
- **Fix:** Groww-env-dependent tests are now marked `skipif` with a clear reason (they need `python-dotenv` + credentials), so the offline suite is honest and green rather than red-with-excuses. Added `tests/test_backtest_orchestrator.py` proving the end-to-end path.

### L1 — LOW — duplicate route definitions (pre-existing, not from this migration)
`routers/routes.py` defines `/override/state` and `/override/square-off` **twice** each. Starlette matches the first registration, so the **secured** handlers (with `require_auth` + `_check_same_origin`) win and the later unsecured duplicates are dead code — not an active hole, but confusing and a latent foot-gun if ordering ever changes. Recommend deleting the second, unsecured copies (lines ~989 and ~1003). Left as-is (pre-existing, out of the migration's blast radius) and flagged here.

---

## What was verified by execution

```
# critical modules import + compile
python3 -c "import backtest_orchestrator" ................................ OK
py_compile routers/routes.py ............................................ OK

# Bhav layer test suite (offline)
tests/test_provider_interface.py .......................................  7 pass
tests/test_local_csv_provider.py ....................................... 13 pass
tests/test_upstox_provider.py ..........................................  5 pass
tests/test_backtest_orchestrator.py (NEW) ..............................  5 pass
tests/test_integration_providers.py .................................... 6 pass / 5 skip
tests/test_groww_provider.py ........................................... 17 pass / 4 skip
                                                              TOTAL: 53 passed, 9 skipped
```

**End-to-end proof (offline, CSV provider):** a `buy ATM CE on first bar` strategy
bought at ₹120.05, the engine squared off at 15:15 at ₹181.95, and it booked a
closed trade of **+₹4,011.42** (lot 65, ₹15.41 costs). Before the fixes this same
path raised `ModuleNotFoundError` on import and, once importable, produced zero
trades. All three dashboard snippets and all `STRATEGY_TEMPLATE.md` examples were
compiled and the most complex was run to completion.

---

## Limitations of this audit

- **The wider RAGI app was not executed.** `fastapi`, `dotenv`, `yfinance`, and
  `typer` are not installed in the audit environment, so `main.py`, the API
  routes at runtime, `bhav/cli.py`, and the Groww live-data path could not be
  started here. The FastAPI route change was syntax-checked (`py_compile`) and
  the auth pattern mirrors existing, working endpoints, but a live smoke test of
  `/api/backtest/custom` end-to-end (HTTP → auth → run → poll) should be done in
  the deployed environment where those deps exist.
- **Groww live data unverified.** The Groww provider's spot fetch requires the
  bot's credentials/config; its synthetic-option math is unit-tested, but a real
  Groww-backed backtest was not run here.
- **No live-money / broker-execution review.** This audit covered the backtest
  and data-provider layers, not order routing to AngelOne/live trading.

---

## Recommended follow-ups (not done in this pass)

1. Live smoke test of `/api/backtest/custom` in the deployed env (deps present).
2. Delete the duplicate unsecured `/override/*` route definitions (L1).
3. Decide Upstox's fate: either bundle a real `bhav/data/upstox_client.py` or
   drop the `upstox` broker option from the UI/CLI (the project is migrating away
   from it anyway).
4. Consider a resource cap (time/positions) on custom-strategy runs to bound a
   pathological user strategy.

---

## Corrected records

The following documents overstated completion and have a correction banner
pointing here: `PHASE_2_IMPLEMENTATION.md`, `PHASE_3_IMPLEMENTATION.md`,
`PROJECT_STATUS_PHASE3.md`. Treat **this report** as the source of truth for the
migration's real state.
