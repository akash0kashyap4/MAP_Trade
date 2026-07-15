"""Lightweight rule-based intraday bias — used only when the premarket
plan/news pipeline is unavailable.

The self-learning brain (AI REQUESTS · MEDIUM/SIGNAL) asked for:

    "A lightweight fallback intraday bias signal (e.g., opening-range breakout
     or VWAP position) that I can use when the premarket news/bias pipeline is
     down."

This module derives a bias purely from today's intraday candles — no network,
no LLM — so that a broken premarket pipeline degrades to a *genuine* (if
lower-confidence) read instead of a blanket no-trade. It is intentionally
conservative: risk_level is always HIGH and strength never exceeds a moderate
value, so downstream sizing/guards stay cautious.

Two independent signals are combined:
  * Opening-Range Breakout (ORB): price above the first-15-min high = bullish,
    below the first-15-min low = bearish, inside the range = neutral.
  * VWAP position: price above the session VWAP = bullish, below = bearish.

Candle rows are the project's standard [timestamp, open, high, low, close,
volume, (oi)] (6 or 7 elements). Indices often report zero volume, in which
case VWAP degrades to a simple typical-price mean (TWAP), matching
indicators.calculator._calc_vwap.
"""
from __future__ import annotations

from typing import Optional

# Public shape mirrors store.premarket_bias so it can be dropped in as a bias:
# {"bias", "bias_strength", "risk_level", "reasoning", "source", "details"}
_SOURCE = "fallback_orb_vwap"


def _neutral(reason: str, details: Optional[dict] = None) -> dict:
    return {
        "bias": "NEUTRAL",
        "bias_strength": 1,
        "risk_level": "HIGH",
        "reasoning": reason,
        "source": _SOURCE,
        "details": details or {},
    }


def _vwap(candles: list) -> Optional[float]:
    """Volume-weighted average of typical price; falls back to TWAP when the
    series has no volume (indices)."""
    tp_sum = 0.0
    vol_sum = 0.0
    tp_simple = 0.0
    n = 0
    for c in candles:
        high, low, close = float(c[2]), float(c[3]), float(c[4])
        vol = float(c[5]) if len(c) > 5 and c[5] is not None else 0.0
        tp = (high + low + close) / 3.0
        tp_sum += tp * vol
        vol_sum += vol
        tp_simple += tp
        n += 1
    if n == 0:
        return None
    if vol_sum > 0:
        return tp_sum / vol_sum
    return tp_simple / n  # TWAP fallback


def compute_fallback_bias(candles: list, opening_range_bars: int = 15) -> dict:
    """Derive an intraday bias from today's 1-minute candles.

    Args:
        candles: today's 1-min candles, [ts, o, h, l, c, v, (oi)] each.
        opening_range_bars: number of leading 1-min bars that define the
            opening range (default 15 = first 15 minutes).

    Returns:
        A bias dict shaped like store.premarket_bias, always tagged
        source="fallback_orb_vwap" and risk_level="HIGH".
    """
    if not candles:
        return _neutral("no intraday candles yet")
    # Sort defensively by timestamp so opening range / last close are correct.
    try:
        candles = sorted(candles, key=lambda c: c[0])
    except Exception:
        pass

    if len(candles) <= opening_range_bars:
        return _neutral(
            f"opening range not complete ({len(candles)}/{opening_range_bars} bars)",
            {"bars": len(candles)},
        )

    or_candles = candles[:opening_range_bars]
    or_high = max(float(c[2]) for c in or_candles)
    or_low = min(float(c[3]) for c in or_candles)
    last_close = float(candles[-1][4])
    vwap = _vwap(candles)

    # Opening-range breakout signal
    if last_close > or_high:
        orb = "BULLISH"
    elif last_close < or_low:
        orb = "BEARISH"
    else:
        orb = "NEUTRAL"

    # VWAP position signal
    if vwap is None:
        vwp = "NEUTRAL"
    elif last_close > vwap:
        vwp = "BULLISH"
    elif last_close < vwap:
        vwp = "BEARISH"
    else:
        vwp = "NEUTRAL"

    details = {
        "orb": orb,
        "vwap_pos": vwp,
        "or_high": round(or_high, 2),
        "or_low": round(or_low, 2),
        "vwap": round(vwap, 2) if vwap is not None else None,
        "last_close": round(last_close, 2),
    }

    # Combine the two signals.
    directional = {"BULLISH", "BEARISH"}
    if orb in directional and orb == vwp:
        bias, strength = orb, 7          # both agree → strongest fallback read
    elif orb in directional and vwp == "NEUTRAL":
        bias, strength = orb, 4          # ORB leads, VWAP silent
    elif vwp in directional and orb == "NEUTRAL":
        bias, strength = vwp, 4          # VWAP leads, still in opening range
    elif orb in directional and vwp in directional and orb != vwp:
        bias, strength = "NEUTRAL", 2    # conflict → stand down
    else:
        bias, strength = "NEUTRAL", 1    # both neutral

    reason = (
        f"Fallback ORB/VWAP (premarket pipeline down): ORB={orb} "
        f"(range {details['or_low']}-{details['or_high']}), "
        f"price {details['last_close']} vs VWAP {details['vwap']} = {vwp}."
    )
    return {
        "bias": bias,
        "bias_strength": strength,
        "risk_level": "HIGH",
        "reasoning": reason,
        "source": _SOURCE,
        "details": details,
    }
