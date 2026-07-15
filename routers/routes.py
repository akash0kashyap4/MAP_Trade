from __future__ import annotations
import asyncio
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from data import database as db
from data.store import store
from groww.oauth import check_api_connection, send_telegram

router = APIRouter()


@router.get("/groww/status")
async def groww_status():
    """Check Groww API connection health."""
    return check_api_connection()


@router.post("/_demo/seed")
async def demo_seed():
    """Load representative sample data into the live store for screenshots.
    Wipes on next bot restart (store is in-memory). Behind basic auth in nginx."""
    from datetime import datetime, timedelta
    import pytz

    IST = pytz.timezone("Asia/Kolkata")
    now = datetime.now(IST)

    def t(mins_ago):
        return (now - timedelta(minutes=mins_ago)).strftime("%H:%M")

    store.prices["NIFTY"].ltp        = 24187.40
    store.prices["NIFTY"].prev_close = 24052.95
    store.prices["NIFTY"].chg        = 134.45
    store.prices["NIFTY"].chg_pct    = 0.56
    store.prices["BANKNIFTY"].ltp        = 58462.10
    store.prices["BANKNIFTY"].prev_close = 58193.20
    store.prices["BANKNIFTY"].chg        = 268.90
    store.prices["BANKNIFTY"].chg_pct    = 0.46
    store.prices["SENSEX"].ltp        = 77384.55
    store.prices["SENSEX"].prev_close = 77084.94
    store.prices["SENSEX"].chg        = 299.61
    store.prices["SENSEX"].chg_pct    = 0.39

    store.india_vix     = 13.42
    store.ai_status     = "in_trade"
    store.feed_status   = "live"
    store.last_tick_time = now.strftime("%H:%M:%S")
    store.tick_count    = 31
    store.next_check_time = (now + timedelta(minutes=5)).strftime("%H:%M")
    store.premarket_bias = {
        "bias": "BULLISH", "bias_strength": 7, "risk_level": "MEDIUM",
        "reasoning": "Positive global cues, VIX subdued at 13.4, Nifty PCR 1.32 supportive. "
                     "Watch 24050 support, 24220 resistance.",
    }
    store.realized_pnl   = 687.57
    store.cumulative_pnl = 4_212.18

    store.positions = [{
        "instrument": "NIFTY", "strike": 24200, "type": "CE", "action": "BUY_CE",
        "expiry": "2026-07-02", "entry": 89.83, "ltp": 102.40,
        "pnl": round((102.40 - 89.83) * 75, 2),
        "sl": 83.16, "target": 103.16, "quantity": 75,
        "entry_time": (now - timedelta(minutes=18)).isoformat(),
        "trade_db_id": None, "signal_id": None,
    }]

    sample_log_buy = {
        "instrument": "NIFTY", "time": t(18),
        "entries": [
            {"stage":"GUARD","step":"CandleData","status":"PASS","detail":"86 candles loaded","data":{}},
            {"stage":"GUARD","step":"FirstCandleBlock","status":"PASS","detail":"past 15-min opening window","data":{}},
            {"stage":"GUARD","step":"VIX","status":"PASS","detail":"VIX=13.42 <= 18.0","data":{"vix":13.42}},
            {"stage":"GUARD","step":"LateDayCutoff","status":"PASS","detail":"before 14:20","data":{}},
            {"stage":"GUARD","step":"ChoppyZone","status":"PASS","detail":"outside 12:40-12:55 window","data":{}},
            {"stage":"GUARD","step":"ExpiryThetaCutoff","status":"PASS","detail":"expiry_day=False, cutoff=13:00","data":{}},
            {"stage":"INFO","step":"ContextBuilt","status":"INFO",
             "detail":"phase=PULLBACK trend=BULLISH vix=13.42 iv=12.5",
             "data":{"spot":24187.4,"atm":24200,"pcr":1.32,"max_pain":24150}},
            {"stage":"AI","step":"AI_Decision","status":"PASS",
             "detail":"BUY_CE conf=8/10",
             "data":{"reasoning":"15m BULLISH structure with PULLBACK phase off support; PCR 1.32 supportive; low VIX favors directional buys."}},
            {"stage":"GUARD","step":"CorrelatedEntry","status":"PASS","detail":"no correlated entries in last 5 min","data":{}},
            {"stage":"GUARD","step":"ATM_IV","status":"PASS","detail":"ATM IV=12.5 <= 18","data":{"atm_iv":12.5}},
            {"stage":"GUARD","step":"OptionChain","status":"PASS","detail":"strike=24200 ltp=88.5 expiry=2026-07-02","data":{}},
            {"stage":"INFO","step":"Slippage","status":"INFO","detail":"quoted=88.5 -> fill@ask=89.83","data":{"quoted":88.5,"fill":89.83}},
            {"stage":"GUARD","step":"Capital","status":"PASS","detail":"cost=Rs6,738 within budget","data":{}},
            {"stage":"EXECUTION","step":"Outcome","status":"INFO",
             "detail":"ENTERED - BUY_CE 24200CE @ 89.83","data":{"sl":83.16,"target":103.16}},
        ],
        "ai": {
            "action":"BUY_CE","confidence":8,
            "trend_read":"15m BULLISH, 5m pullback to EMA21",
            "entry_trigger":"pullback-to-support near 24150",
            "reasoning":"Bullish 15m structure with PULLBACK phase off support; PCR 1.32 supportive; low VIX favors directional buys.",
            "sl_premium":83.16,"target_premium":103.16,"risk_reward":2.0,
        },
        "outcome": {"result":"ENTERED","detail":"BUY_CE 24200CE @ 89.83"},
    }

    sample_log_skip_vix = {
        "instrument": "BANKNIFTY", "time": t(22),
        "entries": [
            {"stage":"GUARD","step":"CandleData","status":"PASS","detail":"86 candles loaded","data":{}},
            {"stage":"GUARD","step":"FirstCandleBlock","status":"PASS","detail":"past 15-min opening window","data":{}},
            {"stage":"GUARD","step":"VIX","status":"BLOCK","detail":"VIX=19.10 > 18.0 - options too expensive","data":{"vix":19.1}},
            {"stage":"EXECUTION","step":"Outcome","status":"INFO","detail":"SKIP - vix_too_high","data":{}},
        ],
        "ai": None,
        "outcome": {"result":"SKIP","detail":"vix_too_high"},
    }

    sample_log_no_trade = {
        "instrument": "SENSEX", "time": t(13),
        "entries": [
            {"stage":"GUARD","step":"CandleData","status":"PASS","detail":"86 candles loaded","data":{}},
            {"stage":"GUARD","step":"FirstCandleBlock","status":"PASS","detail":"past 15-min opening window","data":{}},
            {"stage":"GUARD","step":"VIX","status":"PASS","detail":"VIX=13.42 <= 18.0","data":{}},
            {"stage":"GUARD","step":"LateDayCutoff","status":"PASS","detail":"before 14:20","data":{}},
            {"stage":"GUARD","step":"ChoppyZone","status":"PASS","detail":"outside 12:40-12:55 window","data":{}},
            {"stage":"GUARD","step":"ExpiryThetaCutoff","status":"PASS","detail":"expiry_day=False","data":{}},
            {"stage":"AI","step":"AI_Decision","status":"INFO",
             "detail":"NO_TRADE conf=5/10",
             "data":{"reasoning":"Mixed signals: 15m RANGING, 5m WEAK_BULLISH, no clear BOS or sweep. Waiting for cleaner setup."}},
            {"stage":"EXECUTION","step":"Outcome","status":"INFO",
             "detail":"NO_TRADE - Mixed signals: 15m RANGING, 5m WEAK_BULLISH","data":{}},
        ],
        "ai": {
            "action":"NO_TRADE","confidence":5,
            "trend_read":"15m RANGING, 5m WEAK_BULLISH, no BOS",
            "entry_trigger":None,
            "reasoning":"Mixed signals: 15m RANGING, 5m WEAK_BULLISH, no clear BOS or sweep. Waiting for cleaner setup.",
        },
        "outcome": {"result":"NO_TRADE","detail":"low conviction"},
    }

    sample_log_blocked_choppy = {
        "instrument": "NIFTY", "time": "12:45",
        "entries": [
            {"stage":"GUARD","step":"CandleData","status":"PASS","detail":"86 candles loaded","data":{}},
            {"stage":"GUARD","step":"FirstCandleBlock","status":"PASS","detail":"past 15-min opening window","data":{}},
            {"stage":"GUARD","step":"VIX","status":"PASS","detail":"VIX=13.42 <= 18.0","data":{}},
            {"stage":"GUARD","step":"LateDayCutoff","status":"PASS","detail":"before 14:20","data":{}},
            {"stage":"GUARD","step":"ChoppyZone","status":"BLOCK","detail":"12:40-12:55 choppy reversal zone (learned)","data":{}},
            {"stage":"EXECUTION","step":"Outcome","status":"INFO","detail":"SKIP - choppy_window","data":{}},
        ],
        "ai": None,
        "outcome": {"result":"SKIP","detail":"choppy_window"},
    }

    store.signals.clear()
    store.add_signal({"time": t(2),  "instrument":"NIFTY",     "action":"BUY_CE",   "confidence":8,
                      "reason":"Bullish 15m + PULLBACK off support, PCR 1.32 supportive",
                      "decision_log": sample_log_buy})
    store.add_signal({"time": t(7),  "instrument":"SENSEX",    "action":"NO_TRADE", "confidence":5,
                      "reason":"Mixed signals: 15m RANGING, 5m WEAK_BULLISH",
                      "decision_log": sample_log_no_trade})
    store.add_signal({"time": "12:45","instrument":"NIFTY",    "action":"SKIP",     "confidence":0,
                      "reason":"12:40-12:55 choppy reversal zone (learned)",
                      "decision_log": sample_log_blocked_choppy})
    store.add_signal({"time": t(22), "instrument":"BANKNIFTY", "action":"SKIP",     "confidence":0,
                      "reason":"VIX=19.10 > 18.0 - options too expensive",
                      "decision_log": sample_log_skip_vix})
    store.add_signal({"time": t(27), "instrument":"NIFTY",     "action":"NO_TRADE", "confidence":6,
                      "reason":"Approaching resistance 24220, awaiting confirmation",
                      "decision_log": None})
    store.add_signal({"time": "09:20","instrument":"NIFTY",    "action":"SKIP",     "confidence":0,
                      "reason":"First 15-min window - fake moves/gap fills",
                      "decision_log": None})

    return {"ok": True, "seeded": {
        "signals": len(store.signals),
        "positions": len(store.positions),
        "ai_status": store.ai_status,
    }}


@router.get("/groww/health")
async def groww_health():
    """Ping Groww API and return connection status."""
    result = check_api_connection()
    if result["ok"]:
        send_telegram("[Ragi] Groww API health check OK.")
    else:
        send_telegram(f"[Ragi] Groww API health check FAILED: {result['message']}")
    return result

_backtest_status = {"running": False, "progress": 0, "result": None, "error": None}


def _check_same_origin(request: Request) -> None:
    """Reject cross-origin mutation requests (CSRF mitigation for non-GET endpoints)."""
    from urllib.parse import urlparse
    origin  = request.headers.get("origin", "")
    referer = request.headers.get("referer", "")
    host    = request.headers.get("host", "").split(":")[0]  # strip port for comparison
    # Allow requests with no Origin/Referer (server-to-server / curl)
    for header_val in (origin, referer):
        if not header_val:
            continue
        parsed_host = urlparse(header_val).hostname or ""
        if host and parsed_host != host:
            raise HTTPException(status_code=403, detail="Cross-origin request rejected")


_VALID_INSTRUMENTS = {"NIFTY", "BANKNIFTY", "SENSEX"}
_VALID_STRATEGIES = {"first_candle", "orb15", "rsi_reversal", "ema_trend", "gap_direction"}
_DATE_RE = r"^\d{4}-\d{2}-\d{2}$"


class BacktestRequest(BaseModel):
    instrument:          str  = "NIFTY"
    start_date:          str  = "2025-01-01"
    end_date:            str  = "2025-05-30"
    use_ai:              bool = False
    strategy:            str  = "first_candle"
    stop_loss_rs:        Optional[float] = None
    target_rs:           Optional[float] = None
    lots:                Optional[int]   = None
    max_trades_per_day:  Optional[int]   = None
    max_daily_loss:      Optional[float] = None

    def validate_request(self):
        import re
        from datetime import datetime
        if self.instrument not in _VALID_INSTRUMENTS:
            raise ValueError(f"instrument must be one of {_VALID_INSTRUMENTS}")
        if self.strategy not in _VALID_STRATEGIES:
            raise ValueError(f"strategy must be one of {_VALID_STRATEGIES}")
        for field_name, date_str in (("start_date", self.start_date), ("end_date", self.end_date)):
            if not re.match(_DATE_RE, date_str):
                raise ValueError(f"{field_name} must be YYYY-MM-DD")
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                raise ValueError(f"{field_name} is not a valid date")
        if self.start_date > self.end_date:
            raise ValueError("start_date must be before end_date")


@router.get("/backtest/strategies")
async def list_strategies():
    from backtest.strategies import STRATEGIES
    return STRATEGIES


@router.get("/status")
async def status():
    return store.sse_payload()


@router.get("/health/pipeline")
async def pipeline_health():
    """Premarket pipeline health for the dashboard.

    `status` is "ok" once the 08:30 premarket plan/news analysis completes,
    "failed" if it errored, or "pending" before it has run. An immediate
    Telegram alert is also raised on failure at market open (see
    trader.pipeline_health_check) — this endpoint lets the UI surface the same
    state without waiting for the end-of-day review.
    """
    return {
        "status":     store.premarket_status,
        "ran_at":     store.premarket_ran_at,
        "error":      store.premarket_error,
        "today_bias": store.premarket_bias.get("bias") if store.premarket_bias else None,
        "alerted":    store.health_alerted,
    }


@router.get("/trades/today")
async def trades_today():
    try:
        return await db.get_today_trades()
    except Exception as e:
        print(f"[trades/today] DB error: {e}")
        return JSONResponse(
            status_code=200,
            content={"error": str(e), "trades": [], "note": "DB unavailable"},
        )


@router.get("/trades")
async def trades(days: int = 30):
    days = max(1, min(days, 365))  # cap between 1 and 365 days
    try:
        return await db.get_trades(days=days)
    except Exception as e:
        print(f"[trades] DB error: {e}")
        return []


@router.get("/rules")
async def rules():
    try:
        return await db.get_latest_rules()
    except Exception as e:
        print(f"[rules] DB error: {e}")
        return {}


@router.post("/backtest/run")
async def backtest_run(req: BacktestRequest, background_tasks: BackgroundTasks):
    try:
        req.validate_request()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if _backtest_status["running"]:
        raise HTTPException(status_code=409, detail="Backtest already running")

    background_tasks.add_task(_run_backtest, req)
    return {"status": "started"}


@router.get("/backtest/status")
async def backtest_status():
    return _backtest_status


def _run_backtest_sync(req: BacktestRequest):
    """Runs in a thread — never blocks the event loop."""
    from backtest.engine import BacktestEngine
    config = {}
    if req.stop_loss_rs:
        config["stop_loss_rs"] = req.stop_loss_rs
    if req.target_rs:
        config["target_rs"] = req.target_rs
    if req.lots:
        config["lots"] = req.lots
    if req.max_trades_per_day:
        config["max_trades_per_day"] = req.max_trades_per_day
    if req.max_daily_loss:
        config["max_daily_loss"] = req.max_daily_loss

    config["strategy"] = req.strategy
    engine = BacktestEngine(use_ai_brain=req.use_ai)
    result = engine.run(req.instrument, req.start_date, req.end_date, config)
    return result, config


async def _run_backtest(req: BacktestRequest):
    _backtest_status["running"] = True
    _backtest_status["error"]   = None
    _backtest_status["result"]  = None
    _backtest_status["trades_done"] = 0
    try:
        loop = asyncio.get_running_loop()
        result, config = await loop.run_in_executor(None, _run_backtest_sync, req)

        stats = {
            "total_trades":  result.total_trades,
            "wins":          result.wins,
            "losses":        result.losses,
            "win_rate":      result.win_rate,
            "total_pnl":     result.total_pnl,
            "profit_factor": result.profit_factor,
            "sharpe_ratio":  result.sharpe_ratio,
            "max_drawdown":  result.max_drawdown,
            "win_rate_by_dow":  result.win_rate_by_day_of_week,
            "win_rate_by_hour": result.win_rate_by_hour,
            "strategy":      result.strategy,
            "instrument":    result.instrument,
            "start_date":    result.start_date,
            "end_date":      result.end_date,
        }
        await db.save_backtest_run({"instrument": req.instrument, **config}, stats)
        _backtest_status["result"] = {**stats, "trades": result.trades[-30:]}

    except Exception as e:
        import traceback
        _backtest_status["error"] = str(e)
        print(f"[backtest] ERROR: {e}\n{traceback.format_exc()}")
    finally:
        _backtest_status["running"] = False


# ── Bhav Engine: Custom Strategy Backtesting ────────────────────────────────

class CustomBacktestRequest(BaseModel):
    """Custom strategy backtest request via Bhav engine."""
    strategy_code: str  # Python code defining `strategy = MyStrategy()`
    start_date: str     # YYYY-MM-DD
    end_date: str       # YYYY-MM-DD
    underlying: str = "NSE_INDEX|Nifty 50"
    capital: float = 500_000
    lot_size: Optional[int] = None
    warmup_days: int = 0
    broker: str = "groww"  # groww, upstox, or csv
    groww_token: Optional[str] = None
    upstox_token: Optional[str] = None
    csv_dir: Optional[str] = None

    def validate(self):
        """Validate request fields."""
        import re
        from datetime import datetime

        if not self.strategy_code or len(self.strategy_code.strip()) < 10:
            raise ValueError("strategy_code must not be empty")
        if self.broker not in ("groww", "upstox", "csv"):
            raise ValueError("broker must be 'groww', 'upstox', or 'csv'")
        for field_name, date_str in (("start_date", self.start_date), ("end_date", self.end_date)):
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
                raise ValueError(f"{field_name} must be YYYY-MM-DD")
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                raise ValueError(f"{field_name} is not a valid date")
        if self.start_date > self.end_date:
            raise ValueError("start_date must be before end_date")


_custom_backtest_status = {"running": False, "progress": 0, "result": None, "error": None}


@router.post("/backtest/custom")
async def custom_backtest(req: CustomBacktestRequest, background_tasks: BackgroundTasks, request: Request):
    """Run custom strategy via Bhav engine with provider selection.

    SECURITY: this endpoint executes arbitrary user-supplied Python
    (`strategy_code`) in-process. That is inherent to a "bring your own
    strategy" feature and cannot be made safe by input validation alone, so it
    is gated behind authentication + same-origin, exactly like the other
    state-changing endpoints. It must only ever be reachable by the
    authenticated operator behind the dashboard login — never exposed publicly.

    Request body:
    {
        "strategy_code": "from bhav.engine.strategy import Strategy, Context\nclass MyStrat(Strategy): ...",
        "start_date": "2025-01-16",
        "end_date": "2025-01-17",
        "underlying": "NSE_INDEX|Nifty 50",
        "capital": 500000,
        "lot_size": 75,
        "warmup_days": 0,
        "broker": "groww"
    }

    Returns immediately with status "started". Poll GET /api/backtest/custom/status for results.
    """
    _check_same_origin(request)
    from main import require_auth  # deferred to avoid circular import at module load
    require_auth(request)

    try:
        req.validate()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    if _custom_backtest_status["running"]:
        raise HTTPException(status_code=409, detail="Custom backtest already running")

    background_tasks.add_task(_run_custom_backtest, req)
    return {"status": "started", "strategy_name": "custom_user_strategy"}


@router.get("/backtest/custom/status")
async def custom_backtest_status():
    """Poll for custom backtest progress and results."""
    return _custom_backtest_status


def _run_custom_backtest_sync(req: CustomBacktestRequest) -> dict:
    """Synchronous backtest execution (runs in thread)."""
    from backtest_orchestrator import run_backtest_async
    from pathlib import Path

    csv_dir = Path(req.csv_dir) if req.csv_dir else None
    cache_dir = Path("cache")  # Use project cache dir

    result = run_backtest_async(
        strategy_code=req.strategy_code,
        start=req.start_date,
        end=req.end_date,
        underlying=req.underlying,
        capital=req.capital,
        lot_size=req.lot_size,
        warmup_days=req.warmup_days,
        broker=req.broker,
        groww_token=req.groww_token,
        upstox_token=req.upstox_token,
        csv_dir=csv_dir,
        cache_dir=cache_dir,
    )
    return result


async def _run_custom_backtest(req: CustomBacktestRequest):
    """Run custom backtest in background and update status."""
    _custom_backtest_status["running"] = True
    _custom_backtest_status["error"] = None
    _custom_backtest_status["result"] = None
    _custom_backtest_status["progress"] = 0

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _run_custom_backtest_sync, req)
        _custom_backtest_status["result"] = result
        _custom_backtest_status["progress"] = 100

        # Optionally save to DB
        try:
            await db.save_backtest_run(
                {
                    "instrument": req.underlying,
                    "broker": req.broker,
                    "strategy": "custom_user_code",
                    "start_date": req.start_date,
                    "end_date": req.end_date,
                },
                {
                    "total_trades": result["total_trades"],
                    "wins": result["wins"],
                    "losses": result["losses"],
                    "win_rate": result["win_rate"],
                    "total_pnl": result["total_pnl"],
                    "profit_factor": result["profit_factor"],
                    "sharpe_ratio": result["sharpe_ratio"],
                    "max_drawdown": result["max_drawdown"],
                },
            )
        except Exception as e:
            print(f"[custom_backtest] Warning: could not save to DB: {e}")

    except Exception as e:
        import traceback
        _custom_backtest_status["error"] = str(e)
        print(f"[custom_backtest] ERROR: {e}\n{traceback.format_exc()}")
    finally:
        _custom_backtest_status["running"] = False


@router.post("/tick")
async def manual_tick(request: Request):
    """Manually trigger one market loop tick (for testing)."""
    trader = request.app.state.trader
    trader._market_open = True
    await trader.market_loop_tick()
    return {"status": "tick done", "signals": len(store.signals)}


@router.get("/positions")
async def positions():
    return store.positions


@router.get("/pnl")
async def pnl():
    return store.get_daily_summary()


# ── Self-learning data feed ───────────────────────────────────────────────────

class TradeImport(BaseModel):
    instrument:  str
    action:      str            # BUY_CE or BUY_PE
    entry_time:  str            # "2025-01-15T09:20:00"
    entry_price: float
    exit_time:   str
    exit_price:  float
    exit_reason: str            # SL / TARGET / EOD / manual
    strike:      Optional[int]  = None
    expiry:      Optional[str]  = None
    quantity:    Optional[int]  = None
    trade_type:  str            = "historical"


@router.post("/trades/import")
async def import_trades(trades: list[TradeImport]):
    """
    Feed historical trades for self-learning.
    The nightly review at 9 PM will analyse these along with paper trades.

    Example body:
    [
      {"instrument":"NIFTY","action":"BUY_CE","entry_time":"2025-01-15T09:20:00",
       "entry_price":120.0,"exit_time":"2025-01-15T10:30:00","exit_price":180.0,
       "exit_reason":"TARGET","strike":24000,"expiry":"2025-01-16","quantity":75}
    ]
    """
    saved = 0
    from config import LOT_SIZES
    for t in trades:
        qty = t.quantity or LOT_SIZES.get(t.instrument, 75)
        pnl_raw = (t.exit_price - t.entry_price) * qty
        brokerage = 40
        await db.insert_trade({
            "trade_type":  t.trade_type,
            "instrument":  t.instrument,
            "action":      t.action,
            "strike":      t.strike,
            "expiry":      t.expiry,
            "entry_time":  t.entry_time,
            "entry_price": t.entry_price,
            "exit_time":   t.exit_time,
            "exit_price":  t.exit_price,
            "exit_reason": t.exit_reason,
            "quantity":    qty,
            "pnl_raw":     round(pnl_raw, 2),
            "pnl_final":   round(pnl_raw - brokerage, 2),
            "signal_id":   None,
        })
        saved += 1
    return {"imported": saved, "message": f"{saved} trades saved. Nightly review at 21:00 will learn from them."}


@router.post("/backtest/run-all")
async def backtest_run_all(req: BacktestRequest, background_tasks: BackgroundTasks):
    """Run all 5 strategies and return comparison results."""
    if _backtest_status["running"]:
        raise HTTPException(status_code=409, detail="Backtest already running")
    background_tasks.add_task(_run_all_strategies, req)
    return {"status": "started"}


async def _run_all_strategies(req: BacktestRequest):
    from backtest.strategies import STRATEGIES
    _backtest_status["running"] = True
    _backtest_status["error"]   = None
    _backtest_status["result"]  = None
    try:
        loop = asyncio.get_running_loop()
        comparison = []

        # Run all 5 rule-based strategies (always without AI so comparison is fair)
        for key, name in STRATEGIES.items():
            result, _ = await loop.run_in_executor(None, _run_backtest_sync,
                BacktestRequest(
                    instrument=req.instrument, start_date=req.start_date,
                    end_date=req.end_date, use_ai=False, strategy=key,
                    stop_loss_rs=req.stop_loss_rs, target_rs=req.target_rs, lots=req.lots,
                ))
            comparison.append({
                "strategy":      name,
                "key":           key,
                "is_ai":         False,
                "total_trades":  result.total_trades,
                "wins":          result.wins,
                "losses":        result.losses,
                "win_rate":      round(result.win_rate, 1),
                "total_pnl":     round(result.total_pnl, 0),
                "profit_factor": round(result.profit_factor, 2) if result.profit_factor != float("inf") else 999,
                "sharpe":        result.sharpe_ratio,
                "max_drawdown":  round(result.max_drawdown, 0),
            })

        # If AI brain requested, run it as a 6th entry for comparison
        if req.use_ai:
            ai_result, _ = await loop.run_in_executor(None, _run_backtest_sync,
                BacktestRequest(
                    instrument=req.instrument, start_date=req.start_date,
                    end_date=req.end_date, use_ai=True, strategy="first_candle",
                    stop_loss_rs=req.stop_loss_rs, target_rs=req.target_rs, lots=req.lots,
                ))
            comparison.append({
                "strategy":      "🤖 AI Brain (Claude)",
                "key":           "ai_brain",
                "is_ai":         True,
                "total_trades":  ai_result.total_trades,
                "wins":          ai_result.wins,
                "losses":        ai_result.losses,
                "win_rate":      round(ai_result.win_rate, 1),
                "total_pnl":     round(ai_result.total_pnl, 0),
                "profit_factor": round(ai_result.profit_factor, 2) if ai_result.profit_factor != float("inf") else 999,
                "sharpe":        ai_result.sharpe_ratio,
                "max_drawdown":  round(ai_result.max_drawdown, 0),
            })

        # Sort by total P&L descending
        comparison.sort(key=lambda x: x["total_pnl"], reverse=True)
        _backtest_status["result"] = {"comparison": comparison, "mode": "all",
                                       "instrument": req.instrument, "use_ai": req.use_ai,
                                       "start": req.start_date, "end": req.end_date}
    except Exception as e:
        import traceback
        _backtest_status["error"] = str(e)
        print(f"[backtest-all] ERROR: {e}\n{traceback.format_exc()}")
    finally:
        _backtest_status["running"] = False


# ── Historical data download ──────────────────────────────────────────────────

_download_status = {"running": False, "result": None, "error": None}


class DataDownloadRequest(BaseModel):
    instrument: str  = "NIFTY"
    date_from:  str  = "2025-01-01"
    date_to:    str  = "2025-03-31"
    type:       str  = "both"   # "spot", "options", "both"


@router.post("/data/download")
async def download_data(req: DataDownloadRequest, background_tasks: BackgroundTasks):
    """
    Download and cache historical candle data from Upstox.
    Runs in background — poll GET /api/data/download/status for progress.
    type: 'spot' | 'options' | 'both'
    """
    if _download_status["running"]:
        raise HTTPException(status_code=409, detail="Download already running")
    background_tasks.add_task(_run_download, req)
    return {"status": "started", "instrument": req.instrument,
            "date_from": req.date_from, "date_to": req.date_to, "type": req.type}


@router.get("/data/download/status")
async def download_status():
    return _download_status


@router.get("/data/cache/stats")
async def cache_stats():
    """Return summary of what's cached locally."""
    from data.candle_cache import get_cache_stats
    return get_cache_stats()


def _run_download_sync(req: DataDownloadRequest) -> dict:
    from groww.data_loader import download_spot_history, download_option_history
    results = {}
    if req.type in ("spot", "both"):
        results["spot"] = download_spot_history(req.instrument, req.date_from, req.date_to)
    if req.type in ("options", "both"):
        results["options"] = download_option_history(req.instrument, req.date_from, req.date_to)
    return results


async def _run_download(req: DataDownloadRequest):
    _download_status["running"] = True
    _download_status["error"]   = None
    _download_status["result"]  = None
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _run_download_sync, req)
        _download_status["result"] = result
    except Exception as e:
        import traceback
        _download_status["error"] = str(e)
        print(f"[download] ERROR: {e}\n{traceback.format_exc()}")
    finally:
        _download_status["running"] = False


@router.post("/learn/run-now")
async def run_learning_now(background_tasks: BackgroundTasks):
    """Trigger nightly self-learning immediately (don't wait for 9 PM)."""
    background_tasks.add_task(_run_learning_sync)
    return {"status": "learning started"}


async def _run_learning_sync():
    from ai.agent import TradingAgent
    from ai.learner import Learner
    agent   = TradingAgent()
    learner = Learner(agent, db)
    await learner.run_nightly_review()
    print("[routes] On-demand learning complete.")


# ── TRADING MODE TOGGLE ───────────────────────────────────────────────────────

class ModeRequest(BaseModel):
    mode: str  # "paper" | "live"


@router.get("/trading/mode")
async def get_trading_mode():
    """Return current trading mode."""
    import config
    return {"mode": "paper" if config.TRADING["paper_trade"] else "live"}


@router.get("/candles")
async def get_candles(instrument: str = "NIFTY", interval: str = "5m"):
    """
    Fetch OHLCV candles for a given instrument and interval via yfinance.
    interval: 1m | 5m | 15m | 1h | 1D
    """
    import yfinance as yf
    import pytz
    from datetime import time as dtime

    YF_MAP = {
        "NIFTY":     "^NSEI",
        "BANKNIFTY": "^NSEBANK",
        "SENSEX":    "^BSESN",
    }
    # interval → (yf_interval, yf_period, max_candles)
    INTERVAL_MAP = {
        "1m":  ("1m",  "1d",  390),
        "5m":  ("5m",  "5d",  200),
        "15m": ("15m", "5d",  100),
        "1h":  ("1h",  "60d", 100),
        "1D":  ("1d",  "1y",  250),
    }

    if interval not in INTERVAL_MAP:
        raise HTTPException(status_code=400, detail=f"Invalid interval. Use: {list(INTERVAL_MAP)}")

    yf_sym = YF_MAP.get(instrument.upper(), "^NSEI")
    yf_interval, yf_period, max_c = INTERVAL_MAP[interval]
    IST = pytz.timezone("Asia/Kolkata")

    try:
        loop = asyncio.get_running_loop()

        def _fetch():
            ticker = yf.Ticker(yf_sym)
            df = ticker.history(period=yf_period, interval=yf_interval)
            return df

        df = await loop.run_in_executor(None, _fetch)
        if df.empty:
            return {"candles": [], "instrument": instrument, "interval": interval}

        candles = []
        for dt, row in df.iterrows():
            try:
                dt_ist = dt.astimezone(IST)
            except Exception:
                dt_ist = dt
            # For intraday intervals filter to market hours
            if interval in ("1m", "5m", "15m", "1h"):
                t = dt_ist.time()
                if not (dtime(9, 15) <= t <= dtime(15, 30)):
                    continue
            candles.append({
                "time":  dt_ist.isoformat(),
                "open":  round(float(row["Open"]),  2),
                "high":  round(float(row["High"]),  2),
                "low":   round(float(row["Low"]),   2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]) if "Volume" in row else 0,
            })

        # Keep latest max_c candles
        candles = candles[-max_c:]
        return {"candles": candles, "instrument": instrument, "interval": interval}
    except Exception as e:
        print(f"[candles] error: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ── CONFIG / RISK READ-OUT ───────────────────────────────────────────────────

@router.get("/config/risk")
async def get_risk_config():
    """Return live risk parameters from config.TRADING for the dashboard settings panel."""
    import config
    t = config.TRADING
    return {
        "paper_trade":         t.get("paper_trade", True),
        "lots":                t.get("lots", 1),
        "max_positions":       t.get("max_positions", 2),
        "max_daily_loss":      t.get("max_daily_loss", 5000),
        "fallback_sl_pct":     t.get("fallback_sl_pct", 0.30),
        "fallback_target_pct": t.get("fallback_target_pct", 0.60),
        "trailing_sl_trigger": t.get("trailing_sl_trigger", 0.40),
        "trailing_sl_step":    t.get("trailing_sl_step", 0.20),
        "min_confidence":      t.get("min_confidence", 1),
        "bot_paused":          store.bot_paused,
        "new_entries_enabled": store.new_entries_enabled,
    }


# ── MANUAL OVERRIDE ───────────────────────────────────────────────────────────

class OverrideStateRequest(BaseModel):
    paused: bool | None = None
    new_entries: bool | None = None


@router.post("/override/state")
async def override_state(req: OverrideStateRequest, request: Request):
    """
    Pause/resume the bot or toggle new-entry flow at runtime.
    Requires authentication. Changes are in-memory (reset on restart).
    """
    _check_same_origin(request)
    from main import require_auth  # deferred to avoid circular import at module load
    require_auth(request)

    changed = {}
    if req.paused is not None:
        store.bot_paused = req.paused
        changed["bot_paused"] = store.bot_paused
    if req.new_entries is not None:
        store.new_entries_enabled = req.new_entries
        changed["new_entries_enabled"] = store.new_entries_enabled

    if not changed:
        raise HTTPException(status_code=400, detail="Provide 'paused' or 'new_entries' in body")

    msg = "[Override] State change: " + ", ".join(f"{k}={v}" for k, v in changed.items())
    print(msg)
    try:
        from groww.oauth import send_telegram
        await send_telegram(f"[Ragi] {msg}")
    except Exception:
        pass

    return {"ok": True, **changed}


@router.post("/override/square-off")
async def emergency_square_off(request: Request):
    """
    Emergency circuit breaker: close all open option positions at market price,
    pause the bot, and broadcast a Telegram notification.
    Requires authentication.
    """
    _check_same_origin(request)
    from main import require_auth
    require_auth(request)

    positions_snapshot = list(store.positions)
    if not positions_snapshot:
        store.bot_paused = True
        return {"ok": True, "closed": 0, "message": "No open positions. Bot paused."}

    closed = []
    errors = []
    for pos in positions_snapshot:
        try:
            ltp   = pos.get("ltp") or pos.get("entry", 0.0)
            qty   = pos.get("quantity", 0)
            pnl   = round((ltp - pos["entry"]) * qty, 2)
            instr = pos["instrument"]
            strike = pos["strike"]
            opt_type = pos["type"]

            store.realized_pnl  = round(store.realized_pnl + pnl, 2)
            store.cumulative_pnl = round(store.cumulative_pnl + pnl, 2)
            store.remove_position(instr, strike, opt_type)

            closed.append({
                "instrument": instr, "strike": strike, "type": opt_type,
                "entry": pos["entry"], "exit": ltp, "pnl": pnl, "qty": qty,
            })
        except Exception as e:
            errors.append(str(e))

    store.bot_paused = True

    summary_lines = [
        f"  {c['instrument']} {c['strike']}{c['type']} entry={c['entry']} exit={c['exit']} pnl=₹{c['pnl']}"
        for c in closed
    ]
    total_pnl = sum(c["pnl"] for c in closed)
    tg_msg = (
        f"[Ragi] 🚨 EMERGENCY SQUARE-OFF\n"
        f"Closed {len(closed)} position(s), total P&L: ₹{total_pnl:,.2f}\n"
        + "\n".join(summary_lines)
        + "\nBot is now PAUSED."
    )
    try:
        from groww.oauth import send_telegram
        await send_telegram(tg_msg)
    except Exception:
        pass

    print(tg_msg)
    return {
        "ok":      True,
        "closed":  len(closed),
        "total_pnl": round(total_pnl, 2),
        "positions": closed,
        "errors":  errors,
        "bot_paused": True,
    }


@router.post("/trading/set-mode")
async def set_trading_mode(req: ModeRequest):
    """
    Switch trading mode at runtime without restarting the bot.
    Switching to 'live' requires AngelOne credentials in env.
    """
    import config

    if req.mode not in ("paper", "live"):
        raise HTTPException(status_code=400, detail="mode must be 'paper' or 'live'")

    if req.mode == "live":
        # Validate AngelOne credentials are configured
        missing = [k for k in ("ANGEL_API_KEY", "ANGEL_CLIENT_ID", "ANGEL_PASSWORD", "ANGEL_TOTP_SECRET")
                   if not config.__dict__.get(k) and not __import__("os").getenv(k, "").strip()]
        if missing:
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": f"Missing env vars: {', '.join(missing)}"}
            )
        # Test AngelOne login
        try:
            from angelone.auth import get_angel_client
            get_angel_client()
        except Exception as e:
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": f"AngelOne login failed: {e}"}
            )

    config.TRADING["paper_trade"] = (req.mode == "paper")
    print(f"[routes] Trading mode changed → {req.mode.upper()}")
    await send_telegram(f"⚙️ Trading mode changed to: {req.mode.upper()}")
    return {"ok": True, "mode": req.mode}


class OverrideModeRequest(BaseModel):
    paused: Optional[bool] = None
    new_entries_enabled: Optional[bool] = None


@router.post("/override/state")
async def set_override_state(req: OverrideModeRequest):
    """Pause/resume the bot and control new entry flow at runtime."""
    if req.paused is not None:
        store.bot_paused = req.paused
    if req.new_entries_enabled is not None:
        store.new_entries_enabled = req.new_entries_enabled
    return {
        "ok": True,
        "bot_paused": store.bot_paused,
        "new_entries_enabled": store.new_entries_enabled,
    }


@router.post("/override/square-off")
async def override_square_off(request: Request):
    """Emergency exit for all positions and pause the bot."""
    trader = request.app.state.trader
    closed_count = await trader.emergency_square_off()
    return {"ok": True, "closed_count": closed_count, "bot_paused": True}
