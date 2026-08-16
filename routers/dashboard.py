"""
Dashboard v2 endpoints — feed the PaperTrade-inspired panels added in
dashboard/index_v2.html. Every route degrades gracefully so a missing
option-chain source or empty DB doesn't break the UI, and each returns a
predictable JSON shape the front-end can render blindly.
"""
from __future__ import annotations
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

import pytz
from fastapi import APIRouter, HTTPException

from config import INSTRUMENTS, LOT_SIZES, TRADING
from data import database as db
from data.store import store
from groww.historical import (
    get_option_chain_rows,
    round_to_atm,
)
from pydantic import BaseModel, Field
import time
import uuid


# ── In-memory paper-trade book ─────────────────────────────────────────────
# The AI trader has its own persistent position tracking; the manual paper
# trade console gets a lightweight parallel book so an operator can practice
# trades without touching the bot's positions or DB rows. Restarts wipe it —
# these are training exercises, not track record.
_paper_book: dict[str, dict] = {}

# ── Chain snapshot cache ───────────────────────────────────────────────────
# One fetch feeds chain-pulse, option-chain AND market-activity, so we cache
# per instrument with a short TTL instead of hammering NSE/Groww 3x per poll.
_chain_cache: dict[str, tuple[float, dict]] = {}   # instrument -> (epoch, snapshot)
_CHAIN_TTL = 20.0

IST = pytz.timezone("Asia/Kolkata")
router = APIRouter(prefix="/api/dashboard", tags=["dashboard-v2"])


def _fetch_chain_snapshot_blocking(instrument: str) -> dict:
    """Blocking fetch of a full per-strike chain snapshot for `instrument`.

    NSE carries NIFTY/BANKNIFTY index chains (richest per-strike data); SENSEX
    lives on BSE so it comes from Groww. Each source is tried and the other is
    used as fallback. Returns {} if nothing is reachable — callers degrade to
    an empty-but-valid shape so the UI never breaks."""
    price_info = store.prices.get(instrument)
    spot = float(price_info.ltp) if price_info else 0.0
    step = 100 if instrument == "SENSEX" else 50

    def _via_nse() -> dict:
        try:
            from data.nse import get_nse_client
            return get_nse_client().get_option_chain_rows(instrument) or {}
        except Exception:
            return {}

    def _via_groww() -> dict:
        if not spot:
            return {}
        from datetime import date as _d, timedelta as _td
        for days_ahead in range(0, 8):
            expiry = (_d.today() + _td(days=days_ahead)).strftime("%Y-%m-%d")
            snap = get_option_chain_rows(INSTRUMENTS[instrument], spot, expiry, step)
            if snap and snap.get("rows"):
                return snap
        return {}

    snap: dict = {}
    if instrument in ("NIFTY", "BANKNIFTY"):
        snap = _via_nse() or _via_groww()
    else:  # SENSEX
        snap = _via_groww() or _via_nse()

    if snap and not snap.get("spot") and spot:
        snap["spot"] = spot
    if snap and not snap.get("atm"):
        snap["atm"] = round_to_atm(snap.get("spot") or spot, step) if (snap.get("spot") or spot) else 0
    return snap or {}


def _days_to_expiry(expiry) -> Optional[int]:
    """Days from today to an expiry string. Handles NSE's 'DD-Mon-YYYY' and
    Groww's ISO 'YYYY-MM-DD'. Returns None if unparseable."""
    if not expiry or not isinstance(expiry, str):
        return None
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            d = datetime.strptime(expiry, fmt).date()
            return max(0, (d - datetime.now(IST).date()).days)
        except ValueError:
            continue
    return None


async def _chain_snapshot(instrument: str) -> dict:
    """Cached async wrapper around the blocking chain fetch."""
    now = time.time()
    hit = _chain_cache.get(instrument)
    if hit and (now - hit[0]) < _CHAIN_TTL:
        return hit[1]
    snap = await asyncio.get_running_loop().run_in_executor(
        None, _fetch_chain_snapshot_blocking, instrument
    )
    if snap:
        _chain_cache[instrument] = (now, snap)
        return snap
    # Serve stale on failure rather than an empty table.
    return hit[1] if hit else {}


# ── Chain pulse ────────────────────────────────────────────────────────────
@router.get("/chain-pulse/{instrument}")
async def chain_pulse(instrument: str):
    """PCR, IV, IV-skew, max-pain, OI changes and Calls-vs-Puts turnover split
    for one index — everything the Chain Pulse panel renders."""
    instrument = instrument.upper()
    if instrument not in INSTRUMENTS:
        raise HTTPException(status_code=404, detail=f"unknown instrument {instrument}")

    step = 100 if instrument == "SENSEX" else 50
    snap = await _chain_snapshot(instrument)
    spot = float(snap.get("spot") or (store.prices.get(instrument).ltp if store.prices.get(instrument) else 0) or 0)
    atm  = snap.get("atm") or (round_to_atm(spot, step) if spot else 0)
    rows = snap.get("rows") or []
    days_to_exp = _days_to_expiry(snap.get("expiry"))

    # Roll a Calls-vs-Puts turnover split off the per-strike rows.
    calls_turnover = puts_turnover = 0.0
    call_oi_chg = put_oi_chg = 0.0
    ivs_call: list[float] = []
    ivs_put: list[float] = []
    for r in rows:
        strike = r.get("strike")
        ce = r.get("ce") or {}
        pe = r.get("pe") or {}
        if isinstance(strike, (int, float)):
            calls_turnover += float(ce.get("turnover", 0) or 0)
            puts_turnover  += float(pe.get("turnover", 0) or 0)
            call_oi_chg    += float(ce.get("chg_oi", 0) or 0)
            put_oi_chg     += float(pe.get("chg_oi", 0) or 0)
            if atm and abs(strike - atm) <= step * 3:
                if ce.get("iv"): ivs_call.append(float(ce["iv"]))
                if pe.get("iv"): ivs_put.append(float(pe["iv"]))

    total_turnover = calls_turnover + puts_turnover
    calls_share = round(calls_turnover / total_turnover * 100, 1) if total_turnover else 50.0

    pcr_oi = snap.get("pcr")
    iv_skew = None
    if ivs_call and ivs_put:
        iv_skew = round(sum(ivs_call)/len(ivs_call) - sum(ivs_put)/len(ivs_put), 2)

    bias = "NEUTRAL"
    writer_note = "balanced"
    if isinstance(pcr_oi, (int, float)):
        if pcr_oi >= 1.2:
            bias, writer_note = "BULLISH", "put writers dominant"
        elif pcr_oi <= 0.8:
            bias, writer_note = "BEARISH", "call writers dominant"

    return {
        "instrument":     instrument,
        "spot":           spot,
        "atm":            atm,
        "bias":           bias,
        "writer_note":    writer_note,
        "pcr_oi":         pcr_oi,
        "pcr_volume":     snap.get("pcr_volume"),
        "atm_iv":         snap.get("atm_iv"),
        "iv_skew":        iv_skew,
        "max_pain":       snap.get("max_pain"),
        "call_oi_chg":    call_oi_chg,
        "put_oi_chg":     put_oi_chg,
        "turnover":       total_turnover,
        "calls_turnover": calls_turnover,
        "puts_turnover":  puts_turnover,
        "calls_share":    calls_share,
        "puts_share":     round(100 - calls_share, 1),
        "days_to_exp":    days_to_exp,
        "expiry":         snap.get("expiry"),
    }


# ── Market activity ────────────────────────────────────────────────────────
@router.get("/market-activity/{instrument}")
async def market_activity(instrument: str, tab: str = "most_traded", limit: int = 5):
    """Top strikes by turnover / OI buildup / gain / loss for the strip below
    the chain pulse. Returns [] silently if no chain data is cached."""
    instrument = instrument.upper()
    if instrument not in INSTRUMENTS:
        raise HTTPException(status_code=404, detail=f"unknown instrument {instrument}")
    limit = max(1, min(limit, 20))

    snap = await _chain_snapshot(instrument)
    rows = snap.get("rows") or []
    flat: list[dict] = []
    for r in rows:
        strike = r.get("strike")
        for opt_type, opt in (("CE", r.get("ce") or {}), ("PE", r.get("pe") or {})):
            if not opt:
                continue
            oi = float(opt.get("oi", 0) or 0)
            chg_oi = float(opt.get("chg_oi", 0) or 0)
            prev_oi = oi - chg_oi
            chg_pct = (chg_oi / prev_oi * 100) if prev_oi > 0 else 0.0
            flat.append({
                "strike":     strike,
                "type":       opt_type,
                "ltp":        opt.get("ltp"),
                "turnover":   float(opt.get("turnover", 0) or 0),
                "oi":         oi,
                "chg_oi":     chg_oi,
                "chg_pct":    round(chg_pct, 2),
            })

    if tab == "top_gainers":
        flat.sort(key=lambda x: x["chg_pct"], reverse=True)
    elif tab == "top_losers":
        flat.sort(key=lambda x: x["chg_pct"])
    elif tab == "oi_buildup":
        flat.sort(key=lambda x: x["chg_oi"], reverse=True)
    else:  # most_traded (default)
        flat.sort(key=lambda x: x["turnover"], reverse=True)

    return {"instrument": instrument, "tab": tab, "rows": flat[:limit]}


# ── Equity curve ───────────────────────────────────────────────────────────
@router.get("/equity-curve")
async def equity_curve(days: int = 30):
    """Cumulative equity time-series for the equity-curve chart."""
    days = max(1, min(days, 365))
    try:
        trades = await db.get_trades(days=days, completed_only=True)
    except Exception:
        trades = []

    trades = [t for t in trades if t.get("exit_time")]
    trades.sort(key=lambda t: t.get("exit_time") or "")

    equity = float(store.initial_capital) - sum(t.get("pnl_final", 0) or 0 for t in trades)
    series: list[dict] = [{"t": None, "equity": round(equity, 2)}]
    for t in trades:
        equity += float(t.get("pnl_final", 0) or 0)
        series.append({
            "t":      t.get("exit_time"),
            "equity": round(equity, 2),
            "pnl":    round(float(t.get("pnl_final", 0) or 0), 2),
        })

    latest = series[-1]["equity"]
    return {
        "days":    days,
        "initial": float(store.initial_capital),
        "current": latest,
        "pct":     round((latest - store.initial_capital) / store.initial_capital * 100, 2)
                   if store.initial_capital else 0.0,
        "series":  series,
    }


# ── Day-wise P&L heatmap ───────────────────────────────────────────────────
@router.get("/daywise-pnl")
async def daywise_pnl(days: int = 180):
    """GitHub-style contribution heatmap of daily net P&L."""
    days = max(30, min(days, 365))
    try:
        trades = await db.get_trades(days=days, completed_only=True)
    except Exception:
        trades = []

    bucket: dict[str, float] = defaultdict(float)
    for t in trades:
        exit_iso = t.get("exit_time")
        if not exit_iso:
            continue
        try:
            d = datetime.fromisoformat(exit_iso).date().isoformat()
        except Exception:
            continue
        bucket[d] += float(t.get("pnl_final", 0) or 0)

    today = datetime.now(IST).date()
    start = today - timedelta(days=days)
    grid = []
    green = red = 0
    total = 0.0
    cursor = start
    while cursor <= today:
        pnl = round(bucket.get(cursor.isoformat(), 0.0), 2)
        grid.append({"date": cursor.isoformat(), "pnl": pnl,
                     "weekday": cursor.weekday()})
        total += pnl
        if pnl > 0: green += 1
        elif pnl < 0: red += 1
        cursor += timedelta(days=1)

    return {"days": days, "total": round(total, 2),
            "green_days": green, "red_days": red, "grid": grid}


# ── Portfolio stats tiles ──────────────────────────────────────────────────
@router.get("/portfolio-stats")
async def portfolio_stats(days: int = 90):
    """Closed trades / win rate / avg win-loss / max drawdown / charges paid."""
    days = max(1, min(days, 365))
    try:
        trades = await db.get_trades(days=days, completed_only=True)
    except Exception:
        trades = []
    trades = [t for t in trades if t.get("exit_time")]

    closed  = len(trades)
    wins    = [t for t in trades if (t.get("pnl_final") or 0) > 0]
    losses  = [t for t in trades if (t.get("pnl_final") or 0) < 0]
    win_rate = round(len(wins) / closed * 100, 1) if closed else 0.0
    avg_win  = round(sum(t.get("pnl_final", 0) for t in wins)   / len(wins),   2) if wins else 0.0
    avg_loss = round(sum(t.get("pnl_final", 0) for t in losses) / len(losses), 2) if losses else 0.0
    charges  = round(sum(float(t.get("fees_total", 0) or 0) for t in trades), 2)

    # Max drawdown across cumulative equity curve.
    eq = float(store.initial_capital)
    peak = eq
    max_dd = 0.0
    trades.sort(key=lambda t: t.get("exit_time") or "")
    for t in trades:
        eq += float(t.get("pnl_final", 0) or 0)
        peak = max(peak, eq)
        dd = peak - eq
        if dd > max_dd:
            max_dd = dd

    return {
        "days":       days,
        "closed":     closed,
        "wins":       len(wins),
        "losses":     len(losses),
        "win_rate":   win_rate,
        "avg_win":    avg_win,
        "avg_loss":   avg_loss,
        "max_dd":     round(max_dd, 2),
        "charges":    charges,
    }


# ── Full option chain (paper-trade table) ──────────────────────────────────
@router.get("/option-chain/{instrument}")
async def option_chain(instrument: str):
    """Full option chain rows for the paper-trade table view. Returns the
    per-strike CE/PE ladder plus the spot, ATM, expiry and headline PCR /
    max-pain so the paper dashboard can render the whole PaperTrade-style
    grid in one call."""
    instrument = instrument.upper()
    if instrument not in INSTRUMENTS:
        raise HTTPException(status_code=404, detail=f"unknown instrument {instrument}")

    step = 100 if instrument == "SENSEX" else 50
    snap = await _chain_snapshot(instrument)
    spot = float(snap.get("spot") or (store.prices.get(instrument).ltp if store.prices.get(instrument) else 0) or 0)
    atm  = snap.get("atm") or (round_to_atm(spot, step) if spot else 0)

    return {
        "instrument": instrument,
        "spot":       spot,
        "atm":        atm,
        "expiry":     snap.get("expiry") or "",
        "pcr":        snap.get("pcr"),
        "max_pain":   snap.get("max_pain"),
        "rows":       snap.get("rows") or [],
    }


# ── Paper-trade order book (manual) ────────────────────────────────────────
class PaperOrder(BaseModel):
    instrument:     str
    strike:         int
    type:           str = Field(pattern=r"^(CE|PE)$")
    side:           str = Field(pattern=r"^(BUY|SELL)$", default="BUY")
    order_type:     str = Field(pattern=r"^(MARKET|LIMIT)$", default="MARKET")
    lots:           int = Field(ge=1, le=99, default=1)
    ltp:            float = 0.0
    sl_premium:     Optional[float] = None
    target_premium: Optional[float] = None
    expiry:         Optional[str] = None


@router.post("/paper/order")
async def paper_order(order: PaperOrder):
    """Accept a manual paper-trade order into the in-memory book. Fills at the
    supplied LTP (paper), returns the order id for the client to display.
    Note: this is NOT the AI trader's flow — it stays isolated so manual
    experiments cannot pollute the bot's stats."""
    instrument = order.instrument.upper()
    if instrument not in INSTRUMENTS:
        raise HTTPException(status_code=400, detail="unknown instrument")
    lot = LOT_SIZES.get(instrument, 65)
    quantity = order.lots * lot
    fill_price = float(order.ltp or 0)
    if fill_price <= 0:
        raise HTTPException(status_code=422, detail="ltp must be positive for paper fill")

    oid = uuid.uuid4().hex[:12]
    now = datetime.now(IST).isoformat()
    _paper_book[oid] = {
        "id":         oid,
        "instrument": instrument,
        "strike":     order.strike,
        "type":       order.type,
        "side":       order.side,
        "order_type": order.order_type,
        "expiry":     order.expiry,
        "quantity":   quantity,
        "lots":       order.lots,
        "entry":      round(fill_price, 2),
        "ltp":        round(fill_price, 2),
        "pnl":        0.0,
        "sl":         order.sl_premium,
        "target":     order.target_premium,
        "entry_time": now,
        "status":     "OPEN",
    }
    return {"order_id": oid, "status": "filled", "fill_price": fill_price, "quantity": quantity}


@router.get("/paper/positions")
async def paper_positions():
    """Live paper-trade positions with LTP refreshed from the shared price
    feed where available."""
    for pos in _paper_book.values():
        if pos["status"] != "OPEN":
            continue
        # Best-effort mark-to-market off whatever the trader loop cached.
        key = f"{pos['instrument']}_{pos['strike']}_{pos['type']}"
        latest = store.option_prices.get(key)
        if latest:
            pos["ltp"] = round(float(latest), 2)
            direction = 1 if pos["side"] == "BUY" else -1
            pos["pnl"] = round((pos["ltp"] - pos["entry"]) * pos["quantity"] * direction, 2)
    open_positions = [p for p in _paper_book.values() if p["status"] == "OPEN"]
    return {"count": len(open_positions), "positions": open_positions}


@router.post("/paper/exit/{order_id}")
async def paper_exit(order_id: str):
    pos = _paper_book.get(order_id)
    if not pos or pos["status"] != "OPEN":
        raise HTTPException(status_code=404, detail="no such open paper order")
    pos["status"]    = "CLOSED"
    pos["exit_time"] = datetime.now(IST).isoformat()
    pos["exit_price"]= pos["ltp"]
    return {"order_id": order_id, "status": "closed",
            "exit_price": pos["ltp"], "pnl": pos["pnl"]}


# ── Strategy library (mirrors PaperTrade's Strategies page) ────────────────
@router.get("/strategies")
async def strategies():
    """Static catalogue of multi-leg strategies the AI is allowed to reason
    about. Feature-flag `enable_multi_leg` in TRADING gates actual execution;
    this endpoint always returns the catalogue so the UI can render it."""
    catalogue = [
        {"name": "Long Call",         "tag": "Bullish",           "legs": ["+ATM CE"],
         "note": "Pay premium for unlimited upside. Loss capped at the premium."},
        {"name": "Long Put",          "tag": "Bearish",           "legs": ["+ATM PE"],
         "note": "Pay premium for downside to zero. Loss capped at the premium."},
        {"name": "Bull Call Spread",  "tag": "Moderately bullish","legs": ["+ATM CE", "-ATM+2 CE"],
         "note": "Buy a call, sell a higher one. Cheaper than a long call, capped upside."},
        {"name": "Bear Put Spread",   "tag": "Moderately bearish","legs": ["+ATM PE", "-ATM-2 PE"],
         "note": "Buy a put, sell a lower one. Defined risk and defined reward."},
        {"name": "Long Straddle",     "tag": "Big move either way","legs": ["+ATM CE", "+ATM PE"],
         "note": "Buy ATM call and put. Needs a move bigger than the combined premium."},
        {"name": "Long Strangle",     "tag": "Big move either way","legs": ["+ATM+2 CE", "-ATM-2 PE"],
         "note": "Cheaper than a straddle using OTM strikes, but needs a larger move."},
        {"name": "Iron Condor",       "tag": "Range-bound",       "legs": ["+ATM-4 PE", "-ATM-2 PE", "-ATM+2 CE", "+ATM+4 CE"],
         "note": "Short strangle with wings. Credit taken, loss capped by the wings."},
        {"name": "Iron Butterfly",    "tag": "Pinned at ATM",     "legs": ["+ATM-2 PE", "-ATM PE", "-ATM CE", "+ATM+2 CE"],
         "note": "Short straddle with wings. Bigger credit than a condor, narrower zone."},
        {"name": "Bull Put Spread",   "tag": "Moderately bullish","legs": ["-ATM PE", "+ATM-2 PE"],
         "note": "Sell a put, buy a lower one. Credit taken, risk defined by the width."},
        {"name": "Bear Call Spread",  "tag": "Moderately bearish","legs": ["-ATM CE", "+ATM+2 CE"],
         "note": "Sell a call, buy a higher one. Credit taken, risk defined by the width."},
        {"name": "Gap Fade",          "tag": "Mean reversion",    "legs": ["ATM opposite"],
         "note": "Sell premium into a gap open expecting it to fill. Intraday signal only."},
        {"name": "Opening Range Breakout", "tag": "Momentum",     "legs": ["+ATM CE/PE"],
         "note": "First 15 minutes sets the range. Enter the break of it."},
    ]
    return {
        "multi_leg_enabled": bool(TRADING.get("enable_multi_leg", False)),
        "strategies":        catalogue,
    }
