"""Chart analysis: compute an indicator snapshot + ASCII sparkline, ask LLM to
read the pattern. Reuses indicators/calculator.py for the numbers.
"""
from __future__ import annotations

import json
from datetime import datetime

import pytz

from indicators.calculator import calculate_all

IST = pytz.timezone("Asia/Kolkata")


def _sparkline(values: list[float], width: int = 40) -> str:
    """Unicode sparkline for a price series."""
    if not values:
        return ""
    chars = "▁▂▃▄▅▆▇█"
    lo, hi = min(values), max(values)
    if hi == lo:
        return chars[0] * min(width, len(values))
    step = max(1, len(values) // width)
    sampled = values[::step][-width:]
    out = []
    for v in sampled:
        idx = int((v - lo) / (hi - lo) * (len(chars) - 1))
        out.append(chars[idx])
    return "".join(out)


def _candles_from_yf(symbol: str, period: str, interval: str) -> list:
    import yfinance as yf
    df = yf.Ticker(symbol).history(period=period, interval=interval)
    if df.empty:
        return []
    df = df.reset_index()
    ts_col = "Datetime" if "Datetime" in df.columns else "Date"
    return [
        [str(row[ts_col]), float(row["Open"]), float(row["High"]),
         float(row["Low"]), float(row["Close"]), int(row["Volume"])]
        for _, row in df.iterrows()
    ]


def chart_snapshot(symbol: str, period: str = "1mo", interval: str = "1d") -> dict:
    """Standalone snapshot — indicators + sparkline + key levels. No LLM."""
    candles = _candles_from_yf(symbol, period, interval)
    if not candles:
        return {"error": "no candles", "symbol": symbol}
    closes = [c[4] for c in candles]
    highs = [c[2] for c in candles]
    lows = [c[3] for c in candles]
    indicators = calculate_all(candles)
    return {
        "symbol": symbol,
        "interval": interval,
        "period": period,
        "as_of": datetime.now(IST).isoformat(timespec="seconds"),
        "last_close": closes[-1],
        "period_high": max(highs),
        "period_low": min(lows),
        "change_pct": round((closes[-1] / closes[0] - 1) * 100, 2) if len(closes) > 1 else 0.0,
        "sparkline": _sparkline(closes),
        "indicators": indicators,
        "candle_count": len(candles),
    }


async def chart_ai_read(symbol: str, agent, period: str = "1mo", interval: str = "1d") -> dict:
    """Snapshot + LLM pattern read."""
    snap = chart_snapshot(symbol, period, interval)
    if "error" in snap:
        return snap
    system = (
        "You are a chart technician. Given indicator values + a sparkline, "
        "identify: (1) primary trend, (2) momentum state, (3) any classic pattern "
        "(breakout/breakdown/consolidation/reversal), (4) key support/resistance "
        "as numbers, (5) one clear if-then trigger. Be brutally concise. No hedging."
    )
    user = f"Chart:\n{json.dumps(snap, default=str)}"
    try:
        snap["ai_read"] = (await agent._ask(system, user)) or ""
    except Exception as e:
        snap["ai_read"] = f"(llm error: {e})"
    return snap
