"""
RAGI -- Self-Learning Options Trading Bot
Nifty / BankNifty / Sensex | Upstox API | Claude Code Brain
Dashboard: http://localhost:8000
"""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
import hmac
import logging
import os
from pathlib import Path
import sys

import uvicorn
from fastapi import Depends, FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from config import IS_PRODUCTION
from auth import (
    COOKIE_NAME, DEFAULT_PASSWORD, SESSION_TTL, check_session, create_session,
    destroy_session, require_user, resolve_bot_password,
)

from data.database import init_db
from data.store import store
from ai.agent import TradingAgent
from ai.learner import Learner
from ai.news import NewsBrain
from ai.reporter import DailyReporter
from bot.trader import LiveTrader
from routers.routes import router as api_router
from routers.sse import sse_endpoint
from scheduler import setup_scheduler
from groww.live_feed import start_feed

BASE_DIR = Path(__file__).parent
# Force UTF-8 stdout/stderr on Windows so Rs and other symbols never crash
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("ragi.main")


# ─── Auth config ────────────────────────────────────────────────────────────
BOT_USERNAME = os.getenv("BOT_USERNAME", "Panda001")
_raw_pw = os.getenv("BOT_PASSWORD")

if not IS_PRODUCTION and not _raw_pw:
    import warnings
    warnings.warn(
        "BOT_PASSWORD env var not set — using insecure default. Set it in .env before deploying.",
        stacklevel=1,
    )

# Refuses to boot on default/missing credentials when ENV=production.
BOT_PASSWORD = resolve_bot_password(
    _raw_pw, IS_PRODUCTION, bool(os.getenv("SESSION_SECRET")), DEFAULT_PASSWORD,
)

# Session primitives now live in auth.py; require_auth kept as a thin alias so any
# lingering `from main import require_auth` callers keep working.
require_auth = require_user


class LoginBody(BaseModel):
    username: str
    password: str

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    print("[main] DB initialized")

    try:
        from data.database import get_today_realized_pnl, get_total_realized_pnl
        store.cumulative_pnl = await get_total_realized_pnl()
        store.realized_pnl   = await get_today_realized_pnl()
        print(f"[main] Cumulative P&L: ₹{store.cumulative_pnl:,.2f} | Today: ₹{store.realized_pnl:,.2f}")
    except Exception as e:
        print(f"[main] WARNING: Could not load P&L from DB: {e}")

    agent      = TradingAgent()
    trader     = LiveTrader(agent)
    learner    = Learner(agent, _DBProxy())
    news_brain = NewsBrain(agent)
    reporter   = DailyReporter(agent)

    from bot.trader import _send_telegram
    sched = setup_scheduler(trader, learner, news_brain=news_brain,
                            reporter=reporter, notify_fn=_send_telegram)
    sched.start()
    print("[main] Scheduler started (news 08:15/12:30 + daily report 15:45 wired)")

    asyncio.create_task(start_feed())
    print("[main] WebSocket feed started")

    asyncio.create_task(trader.sl_monitor_loop())
    print("[main] SL monitor loop started (60-second interval)")

    # Recover any open positions from database on startup
    asyncio.create_task(trader.recover_active_positions())

    # If bot starts after 8:30 (missed the cron), run premarket analysis immediately
    from datetime import datetime
    import pytz
    from config import is_market_day
    _now = datetime.now(pytz.timezone("Asia/Kolkata"))
    _mins = _now.hour * 60 + _now.minute
    if is_market_day(_now.date()) and _mins >= 8 * 60 + 30:
        async def _late_start():
            await news_brain.scan()          # news first, so premarket plan sees it
            await trader.premarket_analysis()
        asyncio.create_task(_late_start())
        print("[main] Late start detected — running news scan + premarket analysis now")
    elif not is_market_day(_now.date()):
        print(f"[main] {_now.date()} is NOT a trading day (weekend or NSE holiday) — skipping premarket")

    app.state.trader     = trader
    app.state.learner    = learner
    app.state.agent      = agent
    app.state.news_brain = news_brain
    app.state.reporter   = reporter

    yield

    sched.shutdown()
    print("[main] Shutdown complete")


class _DBProxy:
    @staticmethod
    async def get_trades(days=30):
        from data.database import get_trades
        return await get_trades(days)

    @staticmethod
    async def save_learning_rules(rules, stats):
        from data.database import save_learning_rules
        return await save_learning_rules(rules, stats)


app = FastAPI(
    title="Ragi Trading Bot",
    lifespan=lifespan,
    # In production the interactive docs and raw schema are disabled so the
    # private API surface (incl. trading-control endpoints) is not published.
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)

# Every /api/* route requires an authenticated session by default. Auth is a
# router-level dependency (not per-handler) so a newly added endpoint is
# protected the moment it ships — the previous per-handler pattern is exactly
# how ~20 routes shipped open. The only public POST /api/login is declared
# directly on `app` below, so it is unaffected by this dependency.
app.include_router(api_router, prefix="/api", dependencies=[Depends(require_user)])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("X-Robots-Tag", "noindex, nofollow")
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' fonts.googleapis.com; "
        "font-src fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'",
    )
    return resp


@app.get("/health")
async def health():
    """Health check for load balancers and uptime monitors."""
    return {"status": "ok", "service": "ragi-bot"}


@app.get("/robots.txt")
async def robots():
    """Private terminal — disallow all crawling."""
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("User-agent: *\nDisallow: /\n")


@app.get("/stream")
async def stream(request: Request):
    # SSE carries the same session cookie as the REST API (EventSource sends
    # cookies on same-origin requests), so it gets the same gate. Anonymous
    # clients are rejected before any store data is streamed.
    require_user(request)
    return sse_endpoint(request)


# ─── Simple brute-force guard ────────────────────────────────────────────────
_LOGIN_MAX_FAILS = 10
_LOGIN_LOCKOUT_SECONDS = 15 * 60  # 15-min lockout window; resets after this
_login_failures: dict[str, tuple[int, float]] = {}  # ip -> (count, first_failure_ts)


def _is_rate_limited(ip: str) -> bool:
    import time
    entry = _login_failures.get(ip)
    if entry is None:
        return False
    count, first_ts = entry
    if time.time() - first_ts > _LOGIN_LOCKOUT_SECONDS:
        _login_failures.pop(ip, None)
        return False
    return count >= _LOGIN_MAX_FAILS


def _record_failure(ip: str) -> None:
    import time
    entry = _login_failures.get(ip)
    if entry is None:
        _login_failures[ip] = (1, time.time())
    else:
        count, first_ts = entry
        _login_failures[ip] = (count + 1, first_ts)


# ─── Auth routes ─────────────────────────────────────────────────────────────
@app.post("/api/login")
async def api_login(body: LoginBody, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if _is_rate_limited(client_ip):
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in 15 minutes.")

    if body.username == BOT_USERNAME and hmac.compare_digest(body.password, BOT_PASSWORD):
        _login_failures.pop(client_ip, None)
        token = create_session()
        resp = JSONResponse({"ok": True})
        resp.set_cookie(
            COOKIE_NAME, token,
            httponly=True, secure=True, samesite="lax",
            max_age=int(SESSION_TTL),
        )
        return resp
    _record_failure(client_ip)
    raise HTTPException(status_code=401, detail="ACCESS DENIED — Invalid credentials")

@app.post("/api/logout")
async def api_logout(request: Request):
    # POST (not GET): logout mutates session state, so it must not be triggerable
    # by a prefetch, an <img> src, or a cross-site GET.
    destroy_session(request.cookies.get(COOKIE_NAME))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE_NAME)
    return resp

# ─── Pages ───────────────────────────────────────────────────────────────────
@app.get("/")
async def login_page():
    return FileResponse(BASE_DIR / "dashboard" / "login.html")

@app.get("/dashboard")
async def dashboard(request: Request):
    if not check_session(request):
        return RedirectResponse("/")
    return FileResponse(BASE_DIR / "dashboard" / "index.html",
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
