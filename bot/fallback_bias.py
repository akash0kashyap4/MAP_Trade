"""
Feature 3: Lightweight fallback intraday bias signal.
Used when premarket news/bias pipeline is down or returned empty.
Based on Opening Range Breakout + VWAP position — no external API needed.
"""
from __future__ import annotations
from indicators.calculator import resample_5min


def calc_fallback_bias(candles_1m: list) -> dict:
    """
    Derive a simple intraday bias from price action alone:
    - Opening Range (9:15-9:45): high/low of first 6 one-min candles
    - VWAP position: is price above or below VWAP?
    - Price vs OR midpoint

    Returns a bias dict matching premarket_bias structure so the rest of
    the bot can use it as a drop-in replacement.
    """
    if not candles_1m or len(candles_1m) < 6:
        return {"bias": "NEUTRAL", "bias_strength": 1, "source": "fallback_insufficient_data"}

    # Opening range = first 30 min (up to 30 candles, but at least 6)
    or_candles = candles_1m[:30]
    or_high = max(float(c[2]) for c in or_candles)
    or_low  = min(float(c[3]) for c in or_candles)
    or_mid  = (or_high + or_low) / 2

    current_close = float(candles_1m[-1][4])

    # VWAP from full session
    cum_vol = cum_vp = 0.0
    for c in candles_1m:
        typical = (float(c[2]) + float(c[3]) + float(c[4])) / 3
        vol = float(c[5]) if c[5] else 0
        cum_vp  += typical * vol
        cum_vol += vol
    vwap = cum_vp / cum_vol if cum_vol > 0 else current_close

    above_vwap = current_close > vwap
    above_or   = current_close > or_high
    below_or   = current_close < or_low
    above_mid  = current_close > or_mid

    # Score: 0-4 bull signals
    bull_signals = sum([above_vwap, above_or, above_mid, current_close > candles_1m[0][1]])
    bear_signals = 4 - bull_signals

    if bull_signals >= 3:
        bias, strength = "BULLISH", min(bull_signals + 3, 7)
    elif bear_signals >= 3:
        bias, strength = "BEARISH", min(bear_signals + 3, 7)
    else:
        bias, strength = "NEUTRAL", 3

    return {
        "bias":              bias,
        "bias_strength":     strength,
        "key_support":       [round(or_low, 0), round(vwap, 0)],
        "key_resistance":    [round(or_high, 0)],
        "risk_level":        "MEDIUM",
        "recommended_stance": "CONSERVATIVE",
        "reasoning":         (
            f"Fallback OR bias: price {'above' if above_or else 'inside/below'} OR "
            f"({or_low:.0f}-{or_high:.0f}), "
            f"{'above' if above_vwap else 'below'} VWAP {vwap:.0f}. "
            f"Bull signals {bull_signals}/4."
        ),
        "source":            "fallback_or_vwap",
        "or_high":           round(or_high, 2),
        "or_low":            round(or_low, 2),
        "vwap":              round(vwap, 2),
    }


def get_effective_bias(premarket_bias: dict, candles_1m: list) -> dict:
    """
    Return premarket_bias if it's valid (came from Claude).
    Fall back to OR/VWAP bias if premarket pipeline was empty/failed.
    """
    if premarket_bias and premarket_bias.get("bias") in ("BULLISH", "BEARISH", "NEUTRAL"):
        if premarket_bias.get("source") != "fallback_or_vwap":
            return premarket_bias  # real premarket bias — use it

    # Pipeline was empty or failed — compute fallback
    fallback = calc_fallback_bias(candles_1m)
    print(f"[fallback_bias] Premarket pipeline empty — using OR/VWAP fallback: "
          f"{fallback['bias']} (strength={fallback['bias_strength']})")
    return fallback
