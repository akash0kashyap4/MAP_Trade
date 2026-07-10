"""
RAGI -- Self-Learning Options Trading Bot
Nifty / BankNifty / Sensex | Upstox API | Claude Code Brain
Dashboard: http://localhost:8000
"""
from __future__ import annotations
import sys
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
# Force UTF-8 stdout/stderr on Windows so Rs and other symbols never crash
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import asyncio
from contextlib import asynccontextmanager
import hashlib
import hmac
import secrets
from datetime import timedelta

import uvicorn
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from data.database import init_db
from data.store import store
from ai.agent import TradingAgent
from ai.learner import Learner
from bot.trader import LiveTrader
from routers.routes import router as api_router
from routers.sse import sse_endpoint
from scheduler import setup_scheduler
from groww.live_feed import start_feed


# ─── Auth config ────────────────────────────────────────────────────────────
BOT_USERNAME = os.getenv("BOT_USERNAME", "Panda001")
BOT_PASSWORD = os.getenv("BOT_PASSWORD", "@Defender@987@")
SESSION_SECRET = os.getenv("SESSION_SECRET", secrets.token_hex(32))
# In-memory session store (token -> True). Fine for single-user.
_sessions: dict[str, bool] = {}

def _make_token() -> str:
    return secrets.token_urlsafe(48)

def _check_session(request: Request) -> bool:
    token = request.cookies.get("ragi_session")
    return bool(token and _sessions.get(token))

def require_auth(request: Request):
    if not _check_session(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

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

    agent   = TradingAgent()
    trader  = LiveTrader(agent)
    learner = Learner(agent, _DBProxy())

    sched = setup_scheduler(trader, learner)
    sched.start()
    print("[main] Scheduler started")

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
        asyncio.create_task(trader.premarket_analysis())
        print("[main] Late start detected — running premarket analysis now")
    elif not is_market_day(_now.date()):
        print(f"[main] {_now.date()} is NOT a trading day (weekend or NSE holiday) — skipping premarket")

    app.state.trader  = trader
    app.state.learner = learner
    app.state.agent   = agent

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


app = FastAPI(title="Ragi Trading Bot", lifespan=lifespan)

app.include_router(api_router, prefix="/api")


@app.get("/stream")
async def stream(request: Request):
    return sse_endpoint(request)


# ─── Auth routes ─────────────────────────────────────────────────────────────
@app.post("/api/login")
async def api_login(body: LoginBody, response: JSONResponse = None):
    if body.username == BOT_USERNAME and body.password == BOT_PASSWORD:
        token = _make_token()
        _sessions[token] = True
        resp = JSONResponse({"ok": True})
        resp.set_cookie(
            "ragi_session", token,
            httponly=True, secure=True, samesite="lax",
            max_age=60 * 60 * 24 * 7  # 7 days
        )
        return resp
    raise HTTPException(status_code=401, detail="ACCESS DENIED — Invalid credentials")

@app.get("/api/logout")
async def api_logout(request: Request):
    token = request.cookies.get("ragi_session")
    if token:
        _sessions.pop(token, None)
    resp = RedirectResponse("/")
    resp.delete_cookie("ragi_session")
    return resp

# ─── Pages ───────────────────────────────────────────────────────────────────
@app.get("/")
async def login_page():
    return FileResponse(BASE_DIR / "dashboard" / "login.html")

@app.get("/dashboard")
async def dashboard(request: Request):
    if not _check_session(request):
        return RedirectResponse("/")
    return FileResponse(BASE_DIR / "dashboard" / "index.html",
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
