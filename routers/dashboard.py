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
    get_option_chain_analytics,
    round_to_atm,
)

IST = pytz.timezone("Asia/Kolkata")
router = APIRouter(prefix="/api/dashboard", tags=["dashboard-v2"])


# ── Chain pulse ────────────────────────────────────────────────────────────
@router.get("/chain-pulse/{instrument}")
async def chain_pulse(instrument: str):
    """PCR, IV, IV-skew, max-pain, OI changes and Calls-vs-Puts turnover split
    for one index — everything the Chain Pulse panel renders."""
    instrument = instrument.upper()
    if instrument not in INSTRUMENTS:
        raise HTTPException(status_code=404, detail=f"unknown instrument {instrument}")

    price_info = store.prices.get(instrument)
    spot = float(price_info.ltp) if price_info else 0.0
    step = 100 if instrument == "SENSEX" else 50
    atm = round_to_atm(spot, step) if spot else 0

    chain = store.option_chain.get(instrument, {}) if isinstance(store.option_chain, dict) else {}
    analytics = chain.get("analytics") if isinstance(chain.get("analytics"), dict) else chain
    rows = chain.get("rows") or []

    # If store has nothing cached yet, try a live pull against the current
    # weekly expiry (the trader tick usually populates this within a minute).
    if not analytics and spot:
        from datetime import date as _d, timedelta as _td
        for days_ahead in range(0, 8):
            expiry = (_d.today() + _td(days=days_ahead)).strftime("%Y-%m-%d")
            try:
                analytics = await asyncio.get_running_loop().run_in_executor(
                    None, get_option_chain_analytics,
                    INSTRUMENTS[instrument], spot, expiry, step,
                )
                if analytics:
                    break
            except Exception:
                continue
    analytics = analytics or {}

    # Roll a Calls-vs-Puts turnover split off whatever rows we have.
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
            call_oi_chg    += float(ce.get("chg_oi", ce.get("oi_change", 0)) or 0)
            put_oi_chg     += float(pe.get("chg_oi", pe.get("oi_change", 0)) or 0)
            if abs(strike - atm) <= step * 3:
                if ce.get("iv"): ivs_call.append(float(ce["iv"]))
                if pe.get("iv"): ivs_put.append(float(pe["iv"]))

    total_turnover = calls_turnover + puts_turnover
    calls_share = round(calls_turnover / total_turnover * 100, 1) if total_turnover else 50.0

    pcr_oi = analytics.get("pcr")
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
        "pcr_volume":     analytics.get("pcr_volume"),
        "atm_iv":         analytics.get("atm_iv"),
        "iv_skew":        iv_skew,
        "max_pain":       analytics.get("max_pain"),
        "call_oi_chg":    call_oi_chg,
        "put_oi_chg":     put_oi_chg,
        "turnover":       total_turnover,
        "calls_turnover": calls_turnover,
        "puts_turnover":  puts_turnover,
        "calls_share":    calls_share,
        "puts_share":     round(100 - calls_share, 1),
        "days_to_exp":    analytics.get("days_to_exp"),
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

    chain = store.option_chain.get(instrument, {}) if isinstance(store.option_chain, dict) else {}
    rows = chain.get("rows") or []
    flat: list[dict] = []
    for r in rows:
        strike = r.get("strike")
        for opt_type, opt in (("CE", r.get("ce") or {}), ("PE", r.get("pe") or {})):
            if not opt:
                continue
            flat.append({
                "strike":     strike,
                "type":       opt_type,
                "ltp":        opt.get("ltp"),
                "turnover":   float(opt.get("turnover", 0) or 0),
                "oi":         float(opt.get("oi", 0) or 0),
                "chg_oi":     float(opt.get("chg_oi", opt.get("oi_change", 0)) or 0),
                "chg_pct":    float(opt.get("chg_pct", 0) or 0),
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
