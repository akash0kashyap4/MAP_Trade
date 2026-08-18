# MAP TRADE Trading Terminal — Enterprise Remediation Blueprint

**Version:** 1.0 · **Date:** 2026-07-12 · **Scope:** akash.mehakva.com / this repository
**Audit baseline:** external enterprise audit scoring 4/10
**Target:** verified 10/10 production-ready for a critical financial system

> Every finding below was re-verified against the code in this repository at commit
> `ce334f7`. Where the audit's claims are stale (already fixed) or where reality is
> **worse** than the audit found, this document says so explicitly, with file:line
> evidence.

---

## 1. Executive Verdict

**Current state: NO-GO for live trading. NO-GO for public exposure of the API.**

The repository is materially better than the audit's 4/10 snapshot in authentication
plumbing (POST-only JSON login with HttpOnly/Secure/SameSite cookies, per-IP login
rate limiting, a logout endpoint, and an auth-gated `/dashboard` all exist in
`main.py`). However, the audit's core conclusion stands, and code review found two
issues the audit missed that are individually launch-blocking:

1. **~20 API routes have no authentication at all** (`routers/routes.py`). This
   includes the unauthenticated **paper→live mode switch** (`POST /api/trading/set-mode`,
   routes.py:803), trade import, demo seed, backtest triggers, data download,
   learning trigger, manual tick, and every read endpoint. The two override
   endpoints are the *only* ones that call `require_auth`.
2. **The active emergency square-off does not place real exit orders.**
   `/api/override/square-off` is registered **twice** (routes.py:735 and
   routes.py:858). FastAPI matches the first registration, which only mutates the
   in-memory `store` — it never calls `trader.emergency_square_off()`. The handler
   that actually exits positions through the trader (routes.py:858) is dead code.
   In live mode, pressing the emergency button would update the dashboard while
   leaving real broker positions open. For a trading system this is the single
   most dangerous defect in the codebase.
3. `/docs`, `/redoc`, and `/openapi.json` are exposed (FastAPI defaults; `main.py:147`
   passes no `docs_url`/`openapi_url` overrides), the SSE `/stream` is
   unauthenticated (`main.py:158`), and default credentials
   (`Panda001` / `ChangeMe123!`) are only warned about, not refused
   (`main.py:47-55`).

**Repo ↔ deployment drift — CONFIRMED, and it is the single biggest structural
risk.** The live-site audit let me pin this down: **production is not running
`main`.** It is running branch **`claude/ragi-bot-improvements-6nyz1v` (commit
`cd4aebb`, "feat: AI learning system — news brain, daily reports, strategy lab")**,
proven by exact-match evidence — only that branch contains the Reports sub-tabs
with the precise stuck `Loading…` strings the audit saw (`dashboard/index.html`
ids `strat-list`, `knowledge-list`, `news-items`) and the `/api/ai/strategies`,
`/api/ai/knowledge`, `/api/news/today` endpoints (`routers/routes.py:893-909`).
None of that exists on `main`.

**Branch relationship (verified with `git merge-base`): `claude/ragi-bot-
improvements-6nyz1v` is a clean *superset* of `main`** — `main` is its ancestor
plus four feature commits. So reconciliation is a fast, conflict-free merge, not a
fork to untangle. **This has now been done:** the deployed branch is merged into
this remediation branch (`claude/ragi-bot-audit-10-10-27njzj`), which is therefore
the single lineage carrying production's AI/news/reports features **and** the
Phase 1 security fixes below. Redeploy production from this branch (Phase 0).

Two audit root-causes are **wrong** when checked against the deployed code:
- (a) `/override/square-off` is **not** duplicated on the deployed branch — the
  §4.1 dead-handler bug is `main`-only and never reached production; the merge
  keeps the single correct handler.
- (b) `loadNewsPulse()` already
  handles the `{date, analysis, items}` object correctly with an empty state
  (`dashboard/index.html:2472-2500`), so "News Pulse expects an array" is not the
  cause. The real defect behind all three stuck Reports tabs is that the Strategy
  Lab / Knowledge Base / News Pulse loader functions are never invoked on sub-tab
  activation — which fits every observed symptom at once: permanent `Loading…`, a
  completely clean console, and the backing APIs returning data when called
  manually. The fix is wiring the tab switch to call the loaders, not changing any
  payload shape.

Two audit findings are genuinely stale even on the deployed branch: the
`method=get` login fallback (the deployed login uses a JS `fetch` POST) and the
"unauthenticated `/dashboard`" claim — that branch **does** gate `/dashboard`
server-side (`main.py:240`, redirect to `/` without a session), so the audit most
likely carried a valid session cookie ("no *visible* session" ≠ no cookie). The
**API routes and `/stream` remain genuinely unauthenticated**, and `/docs` +
`/openapi.json` remain genuinely exposed — those critical findings stand.

**Action item zero (now the highest-priority task): reconcile the two branches**
before any other fix, so remediation lands on the lineage production actually
deploys from. Recommended path in §3 Phase 0. Findings verified against the
deployed branch are marked *[deployed:cd4aebb]*; findings specific to `main` are
marked *[main-only]*.

---

## 2. Target 10/10 Definition

The system is 10/10 production-ready when all of the following are simultaneously
true and verified by automated tests plus a manual smoke pass:

| # | Property | Verification |
|---|----------|--------------|
| 1 | Zero endpoint returns trading data or accepts state change without a valid session | pytest suite S-1…S-8 (§11) |
| 2 | Operator-destructive actions (square-off, live switch) require explicit server-verified intent | pytest SF-1…SF-4 |
| 3 | Emergency square-off provably exits positions through the trader/broker path | pytest SF-5 + manual paper-mode smoke |
| 4 | API schema (`/docs`, `/openapi.json`) unreachable in production | pytest S-7, deploy gate |
| 5 | Production refuses to boot with default credentials | pytest S-8 |
| 6 | Every data-driven panel renders loading/empty/error/disconnected states distinctly | Playwright FE-1…FE-6 |
| 7 | Usable at 320px with no horizontal overflow; keyboard + screen-reader navigable | Playwright R-1…R-4, A11y-1…A11y-4 |
| 8 | Security headers (HSTS, CSP, XCTO, Referrer-Policy, frame-ancestors) present on every response | header check in CI + curl smoke |
| 9 | No redundant polling; data-fetch strategy documented | code review + network-tab smoke |
| 10 | Rollback plan tested; residual risks documented with owners | §13, §14 |

Anything less is not 10/10, regardless of how the UI looks.

---

## 3. Severity-Based Remediation Roadmap

Ordered execution sequence. Do not reorder security below polish.

### Phase 0 — Reconcile branches, establish one deploy lineage ✅ DONE
`claude/ragi-bot-improvements-6nyz1v` (`cd4aebb`) is a superset of `main`, so the
merge was clean.
- **P0.0 ✅** Merged the deployed branch into `claude/ragi-bot-audit-10-10-27njzj`;
  it now carries production's features + the Phase 1 fixes, with a single correct
  override handler.
- **P0.1** ☐ Redeploy production from this branch; add its SHA to the dashboard
  footer so future drift is visible. (deploy action — owner: Akash)

### Phase 1 — Critical, server-side — LARGELY DONE (this branch)
- **P1.1 n/a** Duplicate registrations were `main`-only; the deployed branch/merge
  has a single override handler. Regression-locked by `test_no_duplicate_route_registrations`.
- **P1.2 ✅** Router-level `Depends(require_user)` on all `/api/*` + `require_user`
  on `/stream` (`main.py`, `auth.py`). Covered by `tests/test_security.py`.
- **P1.3 ✅** `docs_url`/`redoc_url`/`openapi_url` disabled when `ENV=production`.
- **P1.4 ✅** `resolve_bot_password()` hard-fails boot on default/missing creds +
  missing `SESSION_SECRET` in production. Unit-tested.
- **P1.5 ☐** Server-side typed-confirmation intent for square-off and live switch
  (§7.2) — still to implement (Phase 2 in progress).
- **P1.6 ✅** `/api/_demo/seed` and `/api/tick` return 404 when `ENV=production`.
- **P1.7** Fix rate limiting behind nginx (X-Forwarded-For) (§4.6).

### Phase 2 — High (2–3 days)
- **P2.1** Security-headers middleware + nginx TLS/HSTS config (§4.7).
- **P2.2** Visible logout control; logout becomes POST (§6.3).
- **P2.3** SSE reconnect/disconnected states; chart timeout/error states (§6.2).
- **P2.4** Typed-confirmation modals for square-off and live switch (§7).
- **P2.5** *[deploy-only]* Fix stuck Reports tabs / News Pulse payload contract (§6.4).
- **P2.6** Mobile responsive layout (§8).

### Phase 3 — Medium (2 days)
- **P3.1** Deduplicate data fetching; single client-side data layer (§9).
- **P3.2** Accessibility landmarks, ARIA, focus order (§8.2).
- **P3.3** Branded 404 + error pages (§10).
- **P3.4** Market Data nav: make distinct or remove *[deploy-only]* (§6.5).

### Phase 4 — Low + hardening (1 day)
- **P4.1** robots.txt, favicon, manifest, meta tags (§10).
- **P4.2** Typography scale bump (§8.3).
- **P4.3** CI release gates (§12), deployment checklist run (§13).

Total estimate: **7–9 working days** for one engineer.

---

## 4. Backend Security Implementation

### 4.1 CRITICAL — Duplicate routes & broken square-off (routes.py:703/844, 735/858)

**Root cause:** two generations of override handlers were both left registered.
FastAPI resolves to the first-registered route, so the *active* handlers are the
auth-wrapped pair at routes.py:703 and 735 — but the active square-off only edits
the in-memory store. The handler that calls `trader.emergency_square_off()`
(routes.py:858, which the tests in `tests/test_api.py` exercise directly) is
unreachable over HTTP.

**Fix:** delete the handlers at routes.py:839-863 (`OverrideModeRequest`,
`set_override_state`, `override_square_off`) and merge the trader call into the
authenticated handler:

```python
@router.post("/override/square-off")
async def emergency_square_off(request: Request, body: ConfirmedAction):
    _check_same_origin(request)
    require_operator(request)                    # §5
    body.verify("SQUARE-OFF")                    # §7.2 typed intent
    trader = request.app.state.trader
    closed_count = await trader.emergency_square_off()   # real exits, incl. broker
    audit_log(request, "square_off", before=len(store.positions), after=0)
    return {"ok": True, "closed_count": closed_count, "bot_paused": True}
```

`LiveTrader.emergency_square_off()` must be the single source of truth for exits
(store mutation + order placement + Telegram). Verify it handles the paper/live
branch; if the store-only P&L bookkeeping in the current routes.py:735 handler is
needed, move it into the trader, never the route.

**Acceptance:** exactly one registration per path (add a startup assertion or test
that `len({r.path for r in app.routes}) == len([r.path for r in app.routes])` per
method); square-off in paper mode with 2 open positions returns `closed_count == 2`
and `store.positions == []`; a mocked live-mode trader receives exit-order calls.

### 4.2 CRITICAL — Authentication on all API routes and SSE

**Root cause:** auth was bolted onto two endpoints via deferred imports
(`from main import require_auth` inside handler bodies, routes.py:710/744) instead
of being a router-level dependency, so every endpoint added since shipped open.

**Fix — structural, so the failure mode can't recur.** Move auth out of `main.py`
into `auth.py` (kills the circular import that caused the deferred-import hack),
then attach it at include time:

```python
# auth.py
from fastapi import HTTPException, Request

def require_user(request: Request) -> None:
    if not check_session(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

def require_operator(request: Request) -> None:
    require_user(request)
    # single-user system today: every authenticated user is the operator.
    # Kept as a distinct dependency so role separation is one function edit away.
```

```python
# main.py
from auth import require_user
app.include_router(api_router, prefix="/api", dependencies=[Depends(require_user)])

@app.get("/stream")
async def stream(request: Request):
    require_user(request)            # SSE uses the same cookie; EventSource sends it
    return sse_endpoint(request)
```

Then create a **separate public router** for the truly public surface, mounted
without the dependency: `POST /api/login` (already app-level in main.py, fine) and
`GET /health`. Everything else inherits 401-by-default. Remove the two inline
`require_auth` calls; the router dependency covers them.

`EventSource` cannot set headers, but it *does* send cookies on same-origin
requests, so cookie-session auth works for `/stream` unchanged. Anonymous
`/stream` must return 401 before the first byte of the stream.

**Acceptance:** the table in §5 — every row's anonymous column returns 401/redirect.

### 4.3 CRITICAL — Docs/OpenAPI lockdown (main.py:147)

```python
# config.py
ENV = os.getenv("ENV", "development")

# main.py
_prod = ENV == "production"
app = FastAPI(
    title="MAP Trade Trading Bot",
    lifespan=lifespan,
    docs_url=None if _prod else "/docs",
    redoc_url=None if _prod else "/redoc",
    openapi_url=None if _prod else "/openapi.json",
)
```

Set `ENV=production` in `deploy/map-trade.service` and `.env.example`. Belt-and-braces:
also block `/docs`, `/redoc`, `/openapi.json` in nginx with `return 404;`.

**Acceptance:** with `ENV=production`, GET /docs, /redoc, /openapi.json → 404.

### 4.4 CRITICAL — Refuse default credentials in production (main.py:47-56)

The current code warns and continues with `ChangeMe123!`. In production this is an
open door with a note taped to it.

```python
if ENV == "production":
    if not _raw_pw or _raw_pw == "ChangeMe123!":
        raise RuntimeError("BOT_PASSWORD must be set to a strong value in production")
    if not os.getenv("SESSION_SECRET"):
        raise RuntimeError("SESSION_SECRET must be set in production")
```

Also: `SESSION_SECRET` (main.py:56) is currently generated and **never used** —
sessions are random opaque tokens in a dict, which is fine, but then delete the
dead variable, or use it to sign tokens if sessions must survive restarts. Dead
security config is worse than none: it implies protection that doesn't exist.
Store password as a hash (`passlib`/`argon2` or at minimum `hashlib.scrypt`)
rather than comparing plaintext, so a leaked env dump doesn't leak the password.

### 4.5 CRITICAL — Kill dev/demo routes in production

`POST /api/_demo/seed` (routes.py:22) overwrites live store state with fake prices,
positions, and P&L — on a trading terminal, an attacker or accident rewriting the
operator's view of open positions is a safety incident, not a cosmetic one. Same
for `POST /api/tick` (routes.py:361) which forces `trader._market_open = True` and
runs a live decision tick.

```python
if ENV != "production":
    router.include_router(dev_router)   # _demo/seed, tick live only in dev
```

The comment "Behind basic auth in nginx" (routes.py:25) is wishful — the shipped
`deploy/map-trade.nginx` has no auth stanza. Never treat comments as controls.

### 4.6 HIGH — Login rate limiting is broken behind nginx (main.py:169-188)

`request.client.host` behind the shipped nginx proxy is always `127.0.0.1`, so all
clients share one failure bucket: 10 failed attempts by *anyone* locks out
*everyone* (attacker-controlled lockout), and per-IP attribution is lost.

Fix: run uvicorn with `--proxy-headers --forwarded-allow-ips 127.0.0.1` (add to
`deploy/map-trade.service` ExecStart) so `request.client.host` reflects
`X-Forwarded-For` — nginx already sets it (`deploy/map-trade.nginx:9`). Additionally,
key the limiter on `(ip, username)` and add a global cap (e.g. 50 failures/15min
across all IPs → alert via Telegram) so a botnet can't brute-force under per-IP
radar. Log every failure with IP + username to the audit log (§7.3).

### 4.7 HIGH — Security headers + TLS

FastAPI middleware (applies to app-served responses everywhere, incl. behind any
future proxy):

```python
@app.middleware("http")
async def security_headers(request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' fonts.googleapis.com; "
        "font-src fonts.gstatic.com; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'",
    )
    return resp
```

(The dashboard uses inline `<script>`/`<style>` and Google Fonts
(login.html:8) — either allow them as above, or better: self-host the two fonts
and move JS to a file, then drop `unsafe-inline` for scripts. Do the CSP in
report-only mode for one day first.)

nginx (`deploy/map-trade.nginx`) must gain a 443 server block (certbot), an 80→443
redirect, `add_header Strict-Transport-Security "max-age=31536000" always;`, and
`return 404` for `/docs|/redoc|/openapi.json`. Note: the `Secure` cookie flag
(main.py:206) means login is **already broken over plain HTTP** — if login
currently works in production, TLS exists (certbot-managed outside the repo);
commit the real nginx config to the repo so it's reviewable.

### 4.8 MEDIUM — CSRF posture

Cookies are `SameSite=lax` (main.py:206), which blocks cross-site POSTs in modern
browsers, and `_check_same_origin` (routes.py:194) adds Origin/Referer checking —
but it's only wired to the two override endpoints, and it **allows requests with
neither header**, which includes non-browser attackers who have somehow obtained a
cookie, but more importantly older/embedded browsers. Actions:
- Apply `_check_same_origin` as a router-level dependency for **all**
  state-changing methods (POST/PUT/DELETE), not per-handler.
- For the two destructive actions, the typed-intent token (§7.2) doubles as a
  CSRF proof (attacker's cross-site request can't know it).
- Change `GET /api/logout` (main.py:213) to POST (a GET that mutates session
  state is CSRF-strikable and gets prefetched by some browsers).

---

## 5. Authentication and Authorization Matrix

Single-user system: `user` and `operator` are the same person today, but the
dependency split (§4.2) keeps the matrix enforceable and future-proof.

| Route | Method | Anonymous | User | Operator | Notes |
|---|---|---|---|---|---|
| `/` (login page) | GET | 200 | 200 | 200 | public |
| `/health` | GET | 200 | 200 | 200 | public, no data |
| `/api/login` | POST | 200/401/429 | — | — | rate-limited |
| `/api/logout` | POST | 401 | 200 | 200 | was GET — change |
| `/dashboard` | GET | 302→/ | 200 | 200 | already enforced ✅ |
| `/stream` (SSE) | GET | **401** | 200 | 200 | currently open ❌ |
| `/api/status,/positions,/pnl,/trades*,/rules,/candles,/config/risk,/trading/mode,/backtest/status,/backtest/strategies,/data/*` | GET | **401** | 200 | 200 | all currently open ❌ |
| `/api/groww/status,/groww/health` | GET | **401** | 200 | 200 | health pings Telegram — abuse vector ❌ |
| `/api/backtest/run,/run-all` | POST | **401** | 403 | 200+CSRF | expensive jobs |
| `/api/data/download` | POST | **401** | 403 | 200+CSRF | expensive |
| `/api/learn/run-now` | POST | **401** | 403 | 200+CSRF | |
| `/api/trades/import` | POST | **401** | 403 | 200+CSRF | mutates learning data |
| `/api/override/state` | POST | 401 ✅ | 403 | 200+CSRF | dedupe (§4.1) |
| `/api/override/square-off` | POST | 401 ✅ | 403 | 200+CSRF+**typed intent** | fix trader call (§4.1) |
| `/api/trading/set-mode` | POST | **401** | 403 | 200+CSRF+**typed intent** | currently fully open ❌❌ |
| `/api/_demo/seed`, `/api/tick` | POST | 404 | 404 | 404 | absent in production |
| `/docs`, `/redoc`, `/openapi.json` | GET | 404 | 404 | 404 | production |

**Unauthorized behavior:** missing/expired session → 401 JSON for `/api/*` and
`/stream`; 302→`/` for HTML pages. Authenticated-but-not-operator → 403 (future).

---

## 6. Frontend Reliability Fixes

`dashboard/index.html` is a 2,114-line single file with inline JS. That's
tolerable for a single-operator tool, but the async handling must become uniform.

### 6.1 Shared async state model

Implement one helper used by every panel:

```js
// states: idle | loading | success | empty | error | stale | disconnected | retrying
function renderPanel(el, state, { data, error, onRetry } = {}) {
  el.dataset.state = state;
  switch (state) {
    case 'loading':      el.innerHTML = spinner('Loading…'); break;
    case 'empty':        el.innerHTML = emptyBox('No data yet'); break;
    case 'error':        el.innerHTML = errorBox(error, onRetry); break;
    case 'disconnected': el.innerHTML = warnBox('Live feed disconnected — retrying…'); break;
    // success: caller renders data
  }
}
```

Wrap every `fetch` in a helper that (a) times out via `AbortController`
(10s default), (b) checks `res.ok` — today almost no call site does
(index.html:1474, 1532, 1547 assume 200+JSON), (c) **treats 401 as
session-expiry and redirects to `/`** — currently an expired cookie leaves every
panel silently frozen, which is exactly the audit's "indefinite waiting" finding.

### 6.2 SSE and chart resilience

`new EventSource('/stream')` (index.html:1065) has no `onerror` handling strategy
beyond browser auto-reconnect. Add: `es.onerror` → set all live widgets to
`disconnected`; track `last message time` and mark data `stale` after 2× the
expected cadence; on reconnect, re-fetch `/api/status` once for a consistent
snapshot. The candles fetch (index.html:2097) gets timeout + error + retry-button
states via the §6.1 helper.

### 6.3 Logout control

`/api/logout` exists (main.py:213) but no dashboard element calls it — an operator
on a shared machine cannot end their session. Add to the top bar:

```html
<button id="btn-logout" aria-label="Log out" onclick="logout()">LOGOUT</button>
<script>
async function logout() {
  await fetch('/api/logout', { method: 'POST', credentials: 'include' });
  window.location.href = '/';
}
</script>
```

### 6.4 *[deployed:cd4aebb]* Reports tabs — corrected diagnosis

The audit's root cause ("News Pulse expects an array, gets an object") is **wrong**.
On the deployed branch, `loadNewsPulse()` (`dashboard/index.html:2472-2500`) already
consumes the `{date, analysis, items}` object correctly and even renders an empty
state. Strategy Lab and Knowledge Base loaders likewise exist. Yet all three sit on
`Loading…` forever with a clean console and working APIs.

**Actual root cause:** the sub-tab switch handler does not call the loader for
these three tabs, so their loader functions never run and their panels keep their
initial `Loading…` placeholder. Daily Reports and AI Requests work because their
loaders *are* wired. Fix = invoke the loader on tab activation:

```js
const REPORT_LOADERS = {
  'daily': loadDailyReports, 'strategy': loadStrategyLab,
  'knowledge': loadKnowledge, 'ai-requests': loadAiRequests, 'news': loadNewsPulse,
};
function showReportTab(key) {
  /* …toggle active panel… */
  REPORT_LOADERS[key]?.();          // the missing call
}
```

Harden while there: each loader wraps its `fetch` in the §6.1 helper (check
`res.ok`, timeout, catch → error panel), and `[]`/empty-object responses render a
styled empty state rather than falling through to the leftover spinner. Add a
regression test (FE-1…FE-3, §11) that activates each tab and asserts the panel
leaves `Loading…`.

### 6.5 Error-shaped 200s

`/api/trades/today` returns HTTP 200 with `{error, trades: [], note}` on DB failure
(routes.py:261-264). Return 503 with the same body instead; the frontend helper
then renders the error state and the audit's "silent empty table" class of bug
disappears. Keeping errors out of the 200 channel also makes uptime monitoring
honest.

---

## 7. Operator Safety UX

### 7.1 What exists / what's missing

Square-off already has a native `confirm()` (index.html:1600, 2054) — better than
the audit's "one-click" claim, but a native confirm is muscle-memory clickable and
carries no server-side proof. The live-mode switch has **no UI in this repo but a
fully open API** (routes.py:803): anyone who can reach the port can flip the bot
to live trading. That is the priority.

### 7.2 Server-verified intent (the control that actually matters)

Client modals are UX; the server must be the enforcement point:

```python
class ConfirmedAction(BaseModel):
    confirm_phrase: str

    def verify(self, expected: str) -> None:
        if self.confirm_phrase != expected:
            raise HTTPException(status_code=428, detail=f"Type {expected!r} to confirm")

@router.post("/trading/set-mode")
async def set_trading_mode(req: ModeRequest, body: ConfirmedAction, request: Request):
    _check_same_origin(request)
    require_operator(request)
    if req.mode == "live":
        body.verify("GO LIVE")           # server rejects unconfirmed live switch
    ...
    audit_log(request, "set_mode", before=old_mode, after=req.mode)
```

Square-off requires `confirm_phrase == "SQUARE-OFF"`. Any request missing or
mismatching the phrase → 428, nothing changes. This simultaneously defeats
accidental clicks, replayed fetches from console history, and CSRF.

### 7.3 Audit log

Append-only table `operator_audit(ts, user, ip, action, prev_state, new_state,
request_id)` written by `audit_log()` for: login success/failure, logout,
square-off, set-mode, override/state, trades/import, backtest/run, data/download,
learn/run-now. The existing Telegram pings (routes.py:727, 787, 835) stay as
notifications but are **not** the audit trail — Telegram delivery is best-effort
and currently swallowed by bare `except: pass`.

### 7.4 Confirmation modal spec (frontend)

Replace `confirm()` with a modal that shows, in plain language: the exact action
("Close ALL open positions at market price"), current mode badge (PAPER/LIVE),
position count and unrealized P&L, consequence ("Bot will be PAUSED"),
reversibility ("Cannot be undone"), a text input requiring the phrase, and a
confirm button labeled with the action ("SQUARE OFF 2 POSITIONS", never "OK") plus
an always-present Cancel. Destructive controls live in a visually separate
red-bordered "danger zone" — `#btn-squareoff` (index.html:836) already has a
`danger` class; extend the pattern to a dedicated zone containing square-off,
pause, and mode switch.

**Acceptance:** single click never triggers square-off; live mode unreachable
without typing "GO LIVE"; `curl -X POST /api/trading/set-mode -d '{"mode":"live"}'`
with a valid cookie but no phrase → 428.

---

## 8. Responsive and Accessibility Upgrade

### 8.1 Responsive (currently zero `@media` queries in 2,114 lines)

Breakpoints to implement and test: 320 / 375 / 390 / 414 / 768 / 1024 / 1440.

- ≤768px: the three-column grid collapses to a single column; left sidebar nav
  becomes a slide-in drawer behind a hamburger (or bottom tab bar); the right AI
  panel moves below main content or into a tab.
- `html, body { overflow-x: hidden }` is a bandage, not a fix — audit each fixed
  `width:` and the tables (`.pos-table`, `.candle-table`) get
  `overflow-x: auto` wrappers so wide data scrolls inside its card.
- Touch targets ≥44px for nav items and danger-zone buttons.

### 8.2 Accessibility

- Landmarks: wrap the sidebar in `<nav aria-label="Main">`, content in `<main>`,
  AI panel in `<aside aria-label="AI Brain">`, top bar in `<header>`. The nav
  items are `onclick` `<div>`s (index.html:625) — convert to `<button>`s (keyboard
  + accessible name for free).
- One `<h1>` (MAP·TRADE / page title), section titles as `<h2>`, card titles `<h3>`.
- The section-switcher (`setNav`) is a tab pattern: `role="tablist"` on the nav,
  `role="tab"` + `aria-selected` per item, `role="tabpanel"` per `.nav-section-panel`,
  arrow-key navigation.
- `aria-label` on every icon-only control; `aria-live="polite"` on the P&L ticker
  and feed-status chip so state changes are announced.
- Visible `:focus-visible` outline (2px cyan) on all interactive elements; verify
  tab order follows visual order.

### 8.3 Typography

Base font is ~11px in many panels (e.g. index.html:262, 304). Move to a scale:
body ≥14px (16px on mobile inputs — prevents iOS zoom), table data ≥12px, labels
≥11px uppercase only with letter-spacing. Contrast-check the dim cyan-on-black
text (`--text-dim`) against WCAG AA (4.5:1).

**Acceptance:** Playwright at 320px shows no horizontal scrollbar; axe-core scan
reports no critical violations; full keyboard walk reaches every control.

---

## 9. Performance and Data Fetching Fixes

Verified callers of `/api/trades/today`: **one** (index.html:1474) — the audit's
"redundantly fetched many times" is either deploy-drift or refers to interval
re-polling. Regardless, formalize the data strategy so it stays clean:

- **SSE is the push channel** for store state (`store.sse_payload()` — status,
  prices, positions, signals, P&L). Any polling of `/api/status` duplicating SSE
  is forbidden.
- **Pull on demand** for heavier/DB data: trades-today (on load + after SSE
  signals a closed trade — not on a blind interval), rules and risk config (on
  load + after settings save), candles (on timeframe switch + 60s refresh while
  the chart tab is visible; pause with `document.visibilityState`).
- One in-flight-request de-dupe map so double-clicks and tab re-entry don't stack
  identical requests:

```js
const inflight = new Map();
function fetchOnce(url, opts) {
  if (!inflight.has(url)) {
    inflight.set(url, apiFetch(url, opts).finally(() => inflight.delete(url)));
  }
  return inflight.get(url);
}
```

- Backtest status polling (index.html:1658/1724/1831 — three copies) collapses
  into one shared poller with backoff and a hard stop.

Document this in `docs/DATA_FLOW.md` (one page: which widget uses which channel).

**Acceptance:** network tab over 5 idle minutes shows only SSE frames + at most
one candles refresh per minute; no duplicate concurrent requests to the same URL.

---

## 10. SEO, PWA, and Public Web Hygiene

Private terminal ⇒ the goal is *non*-discovery and honest error surfaces.

- **robots.txt** (serve at `/robots.txt`):
  ```
  User-agent: *
  Disallow: /
  ```
  (Disallow everything — there is no public content worth indexing; do not
  enumerate private paths like `/dashboard` in robots.txt, that's a signpost.)
  Add `<meta name="robots" content="noindex, nofollow">` to both HTML pages and
  `X-Robots-Tag: noindex` via the headers middleware.
- **Branded 404/error page:** FastAPI exception handler returning a minimal dark
  page matching the terminal theme (and JSON for `/api/*` paths).
- **Favicon** (`/favicon.ico` + `<link rel="icon">`), **manifest.json** with name,
  theme color `#00d4ff`, icons — makes iPad-on-desk installs clean.
- Meta description + canonical on `/` only; no Open Graph needed (nothing should
  be shared socially from a private terminal — a bare og:title is fine).
- Self-host the Google Fonts (login.html:8, index.html) — removes a third-party
  request that leaks the terminal's existence to font CDN logs and simplifies CSP.

---

## 11. Automated Test Strategy

Extend the existing pytest suite (`tests/test_api.py` currently calls route
functions directly — it exercised the *dead* square-off handler, which is how the
§4.1 bug survived; new tests must go through `httpx.AsyncClient(app=...)` so
routing, dependencies, and middleware are actually under test).

**API security (pytest, blocking):**
- S-1 `anonymous_sensitive_api_denied` — parametrized over every row of §5's
  matrix: anonymous request → 401.
- S-2 `anonymous_dashboard_redirects` — no data in body.
- S-3 `anonymous_sse_denied` — `/stream` → 401 before any event bytes.
- S-4 `docs_disabled_in_production` / S-5 `openapi_disabled_in_production` —
  with `ENV=production` → 404.
- S-6 `demo_seed_absent_in_production` — 404, and `store` unchanged.
- S-7 `route_paths_unique` — no duplicate (method, path) registrations.
- S-8 `boot_refuses_default_password` — `ENV=production` + unset `BOT_PASSWORD`
  → `RuntimeError`.
- S-9 `login_rate_limit_per_ip` — 10 failures from IP A → 429 for A, 200-path
  still open for IP B (via X-Forwarded-For with proxy headers on).
- S-10 `credentials_never_in_query` — assert login route rejects GET (405).

**Safety (pytest, blocking):**
- SF-1 `square_off_requires_confirmation_phrase` — authed POST without phrase → 428.
- SF-2 `live_mode_requires_confirmation_phrase` — 428; mode still `paper`.
- SF-3 `square_off_calls_trader` — mock `app.state.trader`, assert
  `emergency_square_off` awaited exactly once; store positions empty after.
- SF-4 `set_mode_audit_logged` — audit row written with before/after.
- SF-5 `non_operator_denied` — placeholder until roles exist; asserts 401 for
  cookie-less, documents 403 contract.

**Frontend (Playwright):**
- FE-1 empty-array responses render empty states (Strategy Lab / KB when built).
- FE-2 News Pulse object payload renders; FE-3 invalid payload → error panel.
- FE-4 SSE server kill → widgets show disconnected within 5s; restore → recover.
- FE-5 logout button visible, click → redirected to `/`, cookie gone.
- FE-6 expired-session API 401 → auto-redirect to login (no frozen panels).

**Responsive/A11y (Playwright + axe-core):**
- R-1…R-4 no horizontal overflow at 320/375/768/1440.
- A11y-1 landmarks exist; A11y-2 all buttons have accessible names;
  A11y-3 tablist semantics valid; A11y-4 focus visible on tab walk.

**Release gate:** any S-* or SF-* failure blocks deploy unconditionally; FE-4/FE-6
(infinite-loading class) block; R-*/A11y-* block after first passing baseline.

---

## 12. CI/CD Release Gates

Extend `.github/workflows/ci.yml`:

```yaml
jobs:
  test:            # existing unit tests
  security-tests:  # S-*, SF-* with ENV=production matrix leg
  e2e:             # uvicorn + Playwright (FE-*, R-*, A11y-*)
  prod-config-check:
    steps:
      - run: |
          ENV=production BOT_PASSWORD=ChangeMe123! python -c "import main" \
            && { echo "default password accepted!"; exit 1; } || true
      - run: |  # boot with prod env, curl the forbidden surface
          test "$(curl -s -o /dev/null -w '%{http_code}' localhost:8000/openapi.json)" = 404
  header-check:
    steps:
      - run: curl -sI localhost:8000/ | grep -qi "x-content-type-options: nosniff"
```

Deployment policy: deploy job `needs: [test, security-tests, e2e,
prod-config-check, header-check]`; first post-remediation deploy requires manual
approval (GitHub environment protection rule); deploys happen only from `main`.

---

## 13. Deployment Checklist (run in order, check every box)

1. ☐ Deployed build == repo `main` (Phase 0 drift check).
2. ☐ `ENV=production`, strong `BOT_PASSWORD`, `SESSION_SECRET` set in service env.
3. ☐ `/docs`, `/redoc`, `/openapi.json` → 404 (curl from outside).
4. ☐ Anonymous curl of every §5 matrix row → 401/302; `/stream` → 401.
5. ☐ nginx: 443 + valid cert, 80→443 redirect, HSTS header, docs paths 404.
6. ☐ uvicorn running with `--proxy-headers`; login lockout keyed to real client IP.
7. ☐ Login works (POST-only), logout button works, session survives page reload.
8. ☐ Square-off in **paper mode with test positions**: modal → typed phrase →
   positions closed **via trader**, Telegram received, audit row written, bot paused.
9. ☐ `set-mode live` without phrase → 428; with phrase but missing Angel creds → 400.
10. ☐ `/api/_demo/seed` and `/api/tick` → 404.
11. ☐ Mobile pass at 375px on a real phone; no horizontal scroll; drawer nav works.
12. ☐ Security headers present on `/`, `/dashboard`, `/api/status` (curl -I).
13. ☐ SSE reconnect: restart service while dashboard open → disconnected banner →
    auto-recovery.
14. ☐ robots.txt / favicon / 404 page live.
15. ☐ Full CI green on the deployed SHA; audit log reviewed after smoke test.

**Rollback plan:** systemd + git deploy — keep the previous release SHA tagged
(`release-prev`); rollback = `git checkout release-prev && systemctl restart map-trade`,
< 2 minutes. Database schema changes in this remediation are additive only (new
`operator_audit` table), so rollback is schema-safe. If a rollback happens while
positions are open, first action after restart is verifying `recover_active_positions`
repopulated the store (log line + `/api/positions`).

---

## 14. Residual Risk Register

| Risk | Severity | Mitigation status | Owner | Deadline |
|---|---|---|---|---|
| Single-factor, single-user auth (no 2FA) | Medium | Accepted for single operator; add TOTP if a second user ever exists | Akash | condition-triggered |
| In-memory sessions/limiter — lost on restart, single-worker only | Low | Accepted (systemd single process); revisit if `--workers > 1` | Akash | on scaling |
| Plaintext password compare in env (until §4.4 hash lands) | Medium | Fix scheduled Phase 1 | Akash | Phase 1 |
| `unsafe-inline` script CSP until JS extracted from index.html | Medium | Phase 3 extraction | Akash | Phase 3 |
| Broker-side failure during square-off (partial exits) | High | Trader must report per-position errors; Telegram + audit row; manual broker check is the operator runbook | Akash | Phase 1 (reporting) |
| yfinance dependency for candles (rate limits, ToS, outages) | Medium | Error states (§6.2) make failure visible; consider broker data feed | Akash | Phase 3+ |
| Telegram notifications best-effort (`except: pass`) | Low | Audit DB is source of truth; log Telegram send failures | Akash | Phase 2 |
| Deploy drift recurring (audit tested a different build) | High | CI deploys from `main` only; SHA shown in dashboard footer | Akash | Phase 4 |

---

## 15. Final Production Sign-Off Criteria & Recommendation

Sign-off requires, in writing (a checked-off copy of this section in the repo):

1. All Critical and High findings (§3 Phases 0–2) closed with linked commits.
2. Security, safety, and E2E suites green in CI on the deployed SHA.
3. §13 checklist executed against the *production* host, all 15 boxes checked.
4. Paper-mode smoke: one full trading-day cycle (premarket → signals → square-off
   drill → EOD) with no silent failures in logs.
5. Residual risk register (§14) reviewed and re-dated.
6. Live-mode enablement is a **separate, later decision** — minimum two weeks of
   clean paper-mode operation after remediation before "GO LIVE" is typed for the
   first time.

### Verdict

**NO-GO today.** The blocking chain is short and unambiguous: unauthenticated
paper→live switch, an emergency square-off that doesn't reach the broker, ~20
open API routes, and exposed API schema. None of these are large engineering
efforts — Phase 1 is one to two days of focused work — but until every one of
them is closed and test-locked, this system must not face the public internet
with real capital behind it.

**GO condition:** Phases 0–2 complete + §13 checklist green ⇒ production-ready
for **paper mode**. Live mode: only after criterion 6 above.
