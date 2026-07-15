"""
Ragi AI Brain — uses Claude Code CLI (claude -p) directly.
No ANTHROPIC_API_KEY needed. Runs through your existing Claude Code session.
"""
from __future__ import annotations
import asyncio
import json
import os
import re
import time

import pytz
from datetime import datetime

from config import LOT_SIZES
from ai.prompts import (
    PREMARKET_SYSTEM, PREMARKET_USER,
    DECISION_SYSTEM, DECISION_USER,
    TRAILING_SL_SYSTEM, TRAILING_SL_USER,
    NIGHTLY_REVIEW_SYSTEM, NIGHTLY_REVIEW_USER,
)
from ai.schema import validate_decision, validate_premarket, validate_trailing_sl

IST = pytz.timezone("Asia/Kolkata")

# Model selection — Haiku 4.5 is fast and cost-efficient for trade decisions.
# Override with CLAUDE_MODEL env var to swap models without code changes.
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5")


def _now_ist() -> str:
    return datetime.now(IST).strftime("%H:%M")


def _today_ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


def _candles_table(candles: list) -> str:
    lines = ["time         | open     | high     | low      | close    | volume"]
    lines.append("-" * 72)
    for c in candles[-10:]:
        ts = str(c[0])
        ts = ts[11:19] if len(ts) > 11 else ts
        lines.append(f"{ts:<13}| {float(c[1]):<9.2f}| {float(c[2]):<9.2f}| {float(c[3]):<9.2f}| {float(c[4]):<9.2f}| {c[5]}")
    return "\n".join(lines)


def _build_decision_user_msg(market_context: dict, context_block: str) -> str:
    """Build the DECISION_USER prompt from a market_context dict."""
    ind  = market_context.get("indicators", {})
    cap  = market_context.get("capital_info", {})
    spot = market_context.get("spot_price", 0)
    instr = market_context.get("instrument", "NIFTY")
    approx_premium = round(spot * 0.01, 0)
    approx_cost    = int(approx_premium * LOT_SIZES.get(instr, 65))
    ps   = market_context.get("price_structure", {})
    or_  = ps.get("opening_range") or {}
    c30  = ps.get("candles_30m_summary") or {}
    opts = market_context.get("options_snapshot", {})

    user_msg = DECISION_USER.format(
        time=market_context.get("time_of_day", _now_ist()),
        date=market_context.get("date", _today_ist()),
        instrument=instr,
        spot_price=spot,
        spot_change_pct=float(market_context.get("spot_change_pct", 0.0)),
        premarket_bias=json.dumps(market_context.get("premarket_bias", {}), indent=2),
        candles_table=_candles_table(market_context.get("last_10_candles", [])),
        c30_open=c30.get("open", "N/A"),
        c30_high=c30.get("high", "N/A"),
        c30_low=c30.get("low", "N/A"),
        c30_close=c30.get("close", "N/A"),
        c30_move=float(c30.get("move") or 0),
        structure_5m=ps.get("structure_5m", "UNKNOWN"),
        structure_15m=ps.get("structure_15m", "UNKNOWN"),
        trend_strength=ps.get("trend_strength", "RANGING"),
        trend_bias=ps.get("trend_bias", "NEUTRAL"),
        phase=ps.get("phase", "UNKNOWN"),
        bos=ps.get("bos") or "None",
        last_swing_high=ps.get("last_swing_high", "N/A"),
        last_swing_low=ps.get("last_swing_low", "N/A"),
        resistance_levels=ps.get("resistance_levels", []),
        support_levels=ps.get("support_levels", []),
        liquidity_sweep=ps.get("liquidity_sweep", "NONE"),
        sweep_level=ps.get("sweep_level", "N/A"),
        range_high=ps.get("range_high", "N/A"),
        range_low=ps.get("range_low", "N/A"),
        or_high=or_.get("high", "N/A"),
        or_low=or_.get("low", "N/A"),
        or_position=or_.get("position", "N/A"),
        rsi=ind.get("rsi", "N/A"),
        vwap=ind.get("vwap", "N/A"),
        price_vs_vwap=ind.get("price_vs_vwap", "N/A"),
        atr=ind.get("atr", "N/A"),
        ema9=ind.get("ema9", "N/A"),
        ema21=ind.get("ema21", "N/A"),
        ema50=ind.get("ema50", "N/A"),
        atm_strike=opts.get("atm_strike", "N/A"),
        pcr=opts.get("pcr", "N/A"),
        max_pain=opts.get("max_pain", "N/A"),
        atm_iv=opts.get("atm_iv", "N/A"),
        atm_ce_oi=opts.get("atm_ce_oi", "N/A"),
        atm_pe_oi=opts.get("atm_pe_oi", "N/A"),
        oi_change=opts.get("oi_change", "N/A"),
        days_to_exp=opts.get("days_to_exp", "N/A"),
        india_vix=opts.get("india_vix", "N/A"),
        is_expiry_day=opts.get("is_expiry_day", False),
        open_positions=json.dumps(market_context.get("open_positions", [])),
        today_pnl=market_context.get("today_pnl", 0.0),
        capital_available=int(cap.get("available", 100000)),
        capital_locked=int(cap.get("locked", 0)),
        capital_used_pct=cap.get("used_pct", 0),
        trade_cost_approx=approx_cost,
    )
    return f"TODAY'S CONTEXT (prior decisions):\n{context_block}\n\n---\n\n{user_msg}"


def _extract_json(text: str) -> dict:
    text = text.strip()
    # Strip markdown code fences if present
    text = re.sub(r"```(?:json)?\s*", "", text).strip("`").strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        return json.loads(match.group())
    return json.loads(text)


def _ask_claude(system: str, user: str, max_retries: int = 2) -> str:
    """
    Call Anthropic API directly using the API key from config.py.
    """
    from anthropic import Anthropic
    from config import ANTHROPIC_API_KEY

    if not ANTHROPIC_API_KEY:
        print("[agent] Error: ANTHROPIC_API_KEY not found in .env")
        return ""

    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    for attempt in range(max_retries + 1):
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                system=system,
                messages=[
                    {"role": "user", "content": user}
                ]
            )
            return response.content[0].text
        except Exception as e:
            print(f"[agent] Anthropic API attempt {attempt+1} error: {e}")
            time.sleep(2)

    return ""


class TradingAgent:
    """
    Ragi's AI brain.
    Every decision goes through the local Claude Code CLI — no API key required.
    Maintains intra-day conversation context by accumulating the day's candle/signal history.
    """

    def __init__(self):
        self._day_context: list[str] = []   # accumulates today's decisions for context

    async def _ask(self, system: str, user: str) -> str:
        """Run blocking Anthropic API call in a thread so the event loop stays free."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _ask_claude, system, user)

    async def premarket_analysis(self, global_data: dict) -> dict:
        user_msg = PREMARKET_USER.format(
            date=_today_ist(),
            sgx_nifty=global_data.get("sgx_nifty", "N/A"),
            sgx_change=global_data.get("sgx_change", 0),
            dow_futures=global_data.get("dow_futures", "N/A"),
            dow_change=global_data.get("dow_change", 0),
            nasdaq_futures=global_data.get("nasdaq_futures", "N/A"),
            nasdaq_change=global_data.get("nasdaq_change", 0),
            crude=global_data.get("crude", "N/A"),
            crude_change=global_data.get("crude_change", 0),
            dxy=global_data.get("dxy", "N/A"),
            india_vix=global_data.get("india_vix", "N/A"),
            prev_nifty=global_data.get("prev_nifty", "N/A"),
            prev_banknifty=global_data.get("prev_banknifty", "N/A"),
            prev_pcr=global_data.get("prev_pcr", "N/A"),
        )

        raw = await self._ask(PREMARKET_SYSTEM, user_msg)
        try:
            result = _extract_json(raw)
        except Exception as e:
            print(f"[agent] premarket parse error: {e}\nRaw: {raw[:300]}")
            return {"bias": "NEUTRAL", "risk_level": "HIGH", "reasoning": raw[:200]}
        result = validate_premarket(result)
        self._day_context.append(f"[08:30 Premarket bias: {result.get('bias')} | {result.get('reasoning','')}]")
        return result

    async def decide_trade(self, market_context: dict) -> dict:
        context_block = "\n".join(self._day_context[-10:]) if self._day_context else "No prior signals today."
        full_user = _build_decision_user_msg(market_context, context_block)
        raw = await self._ask(DECISION_SYSTEM, full_user)

        try:
            decision = _extract_json(raw)
        except Exception as e:
            print(f"[agent] decide parse error: {e}\nRaw: {raw[:300]}")
            decision = {
                "action": "NO_TRADE",
                "instrument": market_context.get("instrument", "NIFTY"),
                "confidence": 0,
                "reasoning": f"parse_error: {raw[:100]}",
            }

        # Pydantic validation - rejects malformed/out-of-range fields
        decision, schema_err = validate_decision(decision)
        if schema_err:
            print(f"[agent] schema validation failed: {schema_err}")

        # Full AI autonomy — no confidence gate. Only zero conf on non-buy actions.
        if decision.get("action") not in ("BUY_CE", "BUY_PE"):
            decision["confidence"] = 0

        # Accumulate context for next tick
        self._day_context.append(
            f"[{market_context.get('time_of_day',_now_ist())} "
            f"{decision.get('instrument','?')} -> {decision.get('action','?')} "
            f"conf={decision.get('confidence',0)} | {str(decision.get('reasoning',''))[:60]}]"
        )

        return decision

    async def check_trailing_sl(self, position: dict, current_price: float) -> dict:
        entry   = position.get("entry", 0)
        qty     = position.get("quantity", 1)
        pnl     = (current_price - entry) * qty
        pnl_pct = ((current_price - entry) / entry * 100) if entry > 0 else 0.0

        user_msg = TRAILING_SL_USER.format(
            instrument=position.get("instrument", ""),
            strike=position.get("strike", ""),
            option_type=position.get("type", ""),
            entry=entry,
            current=current_price,
            current_sl=position.get("sl", 0),
            pnl=pnl,
            pnl_pct=pnl_pct,
            time=_now_ist(),
        )

        raw = await self._ask(TRAILING_SL_SYSTEM, user_msg)
        try:
            parsed = _extract_json(raw)
        except Exception:
            return {"action": "HOLD", "new_sl": None, "reason": "parse error"}
        return validate_trailing_sl(parsed)

    async def nightly_review(self, trades: list) -> dict:
        wins      = [t for t in trades if t.get("pnl_final", 0) > 0]
        losses    = [t for t in trades if t.get("pnl_final", 0) <= 0]
        total_pnl = sum(t.get("pnl_final", 0) for t in trades)
        win_rate  = len(wins) / len(trades) * 100 if trades else 0

        trades_table = "\n".join(
            f"{t.get('entry_time','?')} | {t.get('instrument','?')} | "
            f"{t.get('action','?')} | P&L=₹{t.get('pnl_final',0):,.0f} | {t.get('exit_reason','?')}"
            for t in trades[-50:]
        )

        user_msg = NIGHTLY_REVIEW_USER.format(
            days=30,
            trades_table=trades_table,
            total=len(trades),
            wins=len(wins),
            losses=len(losses),
            win_rate=win_rate,
            total_pnl=total_pnl,
        )

        raw = await self._ask(NIGHTLY_REVIEW_SYSTEM, user_msg)
        try:
            return _extract_json(raw)
        except Exception as e:
            print(f"[agent] nightly_review parse error: {e}")
            return {"key_insight": raw[:300]}

    def decide_trade_sync(self, market_context: dict) -> dict:
        """Synchronous version for backtest — calls _ask_claude directly, no asyncio."""
        context_block = "\n".join(self._day_context[-10:]) if self._day_context else "No prior signals today."
        full_user = _build_decision_user_msg(market_context, context_block)
        raw = _ask_claude(DECISION_SYSTEM, full_user)

        try:
            decision = _extract_json(raw)
        except Exception as e:
            print(f"[agent-sync] parse error: {e} | raw: {raw[:200]}")
            return {"action": "NO_TRADE", "confidence": 0, "reasoning": f"parse_error: {raw[:100]}"}

        decision, schema_err = validate_decision(decision)
        if schema_err:
            print(f"[agent-sync] schema validation failed: {schema_err}")

        if decision.get("action") not in ("BUY_CE", "BUY_PE"):
            decision["confidence"] = 0

        return decision

    def reset_daily_context(self):
        self._day_context = []
