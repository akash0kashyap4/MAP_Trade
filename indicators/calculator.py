from __future__ import annotations
from typing import Optional

import numpy as np
import pandas as pd

try:
    import pandas_ta as ta
    PANDAS_TA = True
except ImportError:
    PANDAS_TA = False


def calculate_all(candles: list) -> dict:
    if len(candles) < 2:
        return {}

    # Ensure all candles have 7 elements (timestamp, open, high, low, close, volume, oi)
    normalized = []
    for c in candles:
        if len(c) == 6:
            normalized.append(list(c) + [0])
        elif len(c) == 7:
            normalized.append(list(c))
        else:
            normalized.append((list(c) + [0] * 7)[:7])

    df = pd.DataFrame(normalized, columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])
    df = df.sort_values("timestamp").reset_index(drop=True)

    for col in ["open", "high", "low", "close", "volume", "oi"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    result: dict = {}

    # RSI(14)
    if PANDAS_TA and len(df) >= 15:
        rsi = ta.rsi(df["close"], length=14)
        result["rsi"] = round(float(rsi.iloc[-1]), 2) if rsi is not None and not rsi.empty else None
    else:
        result["rsi"] = _calc_rsi(df["close"].tolist(), 14)

    # EMAs
    for period in [9, 21, 50]:
        if len(df) >= period:
            result[f"ema{period}"] = round(float(df["close"].ewm(span=period, adjust=False).mean().iloc[-1]), 2)
        else:
            result[f"ema{period}"] = None

    # VWAP (session) — indices have no volume so falls back to TWAP
    result["vwap"] = _calc_vwap(df)

    # Supertrend(10, 3)
    if PANDAS_TA and len(df) >= 10:
        st = ta.supertrend(df["high"], df["low"], df["close"], length=10, multiplier=3)
        if st is not None and not st.empty:
            col = [c for c in st.columns if "SUPERTd" in c]
            if col:
                direction = int(st[col[0]].iloc[-1])
                result["supertrend_direction"] = "UP" if direction == 1 else "DOWN"
            else:
                result["supertrend_direction"] = "UNKNOWN"
        else:
            result["supertrend_direction"] = "UNKNOWN"
    else:
        result["supertrend_direction"] = "UNKNOWN"

    # Bollinger Bands(20, 2)
    if len(df) >= 20:
        mid = df["close"].rolling(20).mean()
        std = df["close"].rolling(20).std()
        result["bb_upper"]  = round(float((mid + 2 * std).iloc[-1]), 2)
        result["bb_middle"] = round(float(mid.iloc[-1]), 2)
        result["bb_lower"]  = round(float((mid - 2 * std).iloc[-1]), 2)
    else:
        result["bb_upper"] = result["bb_middle"] = result["bb_lower"] = None

    # ATR(14)
    if len(df) >= 15:
        if PANDAS_TA:
            atr = ta.atr(df["high"], df["low"], df["close"], length=14)
            result["atr"] = round(float(atr.iloc[-1]), 2) if atr is not None and not atr.empty else None
        else:
            result["atr"] = _calc_atr(df, 14)
    else:
        result["atr"] = None

    # Volume ratio — N/A for indices (no volume data)
    if len(df) >= 20 and df["volume"].sum() > 0:
        avg_vol = df["volume"].rolling(20).mean().iloc[-1]
        result["volume_ratio"] = round(float(df["volume"].iloc[-1] / avg_vol), 2) if avg_vol > 0 else None
    else:
        result["volume_ratio"] = None

    # OI change % (last candle vs 10 candles ago)
    if len(df) >= 11:
        oi_now  = df["oi"].iloc[-1]
        oi_prev = df["oi"].iloc[-10]
        result["oi_change_pct"] = round(((oi_now - oi_prev) / oi_prev * 100), 2) if oi_prev else 0.0
    else:
        result["oi_change_pct"] = 0.0

    # Trend direction from EMA alignment
    e9  = result.get("ema9")
    e21 = result.get("ema21")
    e50 = result.get("ema50")
    if e9 and e21 and e50:
        if e9 > e21 > e50:
            result["trend"] = "UP"
        elif e9 < e21 < e50:
            result["trend"] = "DOWN"
        else:
            result["trend"] = "SIDEWAYS"
    else:
        result["trend"] = "UNKNOWN"

    # Price vs VWAP
    ltp   = float(df["close"].iloc[-1])
    vwap  = result.get("vwap")
    if vwap:
        result["price_vs_vwap"] = "ABOVE" if ltp >= vwap else "BELOW"
    else:
        result["price_vs_vwap"] = "UNKNOWN"

    # RSI zone
    rsi_val = result.get("rsi")
    if rsi_val is not None:
        if rsi_val >= 70:
            result["rsi_zone"] = "OVERBOUGHT"
        elif rsi_val <= 30:
            result["rsi_zone"] = "OVERSOLD"
        else:
            result["rsi_zone"] = "NEUTRAL"
    else:
        result["rsi_zone"] = "UNKNOWN"

    result["ltp"] = round(ltp, 2)
    return result


# ── price structure helpers ───────────────────────────────────────────────────

def _find_swings(highs: list, lows: list, confirm: int = 2):
    """Pivot swing detection with N-bar confirmation on each side."""
    n = len(highs)
    sh, sl = [], []
    for i in range(confirm, n - confirm):
        if all(highs[i] >= highs[i - j] for j in range(1, confirm + 1)) and \
           all(highs[i] >= highs[i + j] for j in range(1, confirm + 1)):
            sh.append(highs[i])
        if all(lows[i] <= lows[i - j] for j in range(1, confirm + 1)) and \
           all(lows[i] <= lows[i + j] for j in range(1, confirm + 1)):
            sl.append(lows[i])
    return sh, sl


def _structure_label(swing_highs: list, swing_lows: list) -> str:
    """HH+HL → BULLISH, LH+LL → BEARISH, else RANGING."""
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        if swing_highs[-1] > swing_highs[-2] and swing_lows[-1] > swing_lows[-2]:
            return "BULLISH"
        if swing_highs[-1] < swing_highs[-2] and swing_lows[-1] < swing_lows[-2]:
            return "BEARISH"
    return "RANGING"


def _resample_to_nmin(candles_5m: list, n: int) -> list:
    """Group 5-min candles into N-min bars (n must be a multiple of 5)."""
    step = n // 5
    out = []
    for i in range(0, len(candles_5m) - step + 1, step):
        group = candles_5m[i : i + step]
        out.append([
            group[0][0],
            float(group[0][1]),
            max(float(c[2]) for c in group),
            min(float(c[3]) for c in group),
            float(group[-1][4]),
            sum(float(c[5]) if c[5] else 0 for c in group),
            0,
        ])
    return out


def _detect_phase(closes: list, trend_bias: str, atr: float) -> str:
    """
    IMPULSE_UP/DOWN  — parabolic spike: ALL 3 of last 3 bars in trend direction
                       AND 30-min move > 1.5×ATR. Do not chase.
    TRENDING_UP/DOWN — steady move: 2 of 3 bars in trend direction but not a spike.
                       Valid entry zone near support/resistance.
    PULLBACK         — counter-trend retracement against the bias (ideal entry).
    CONSOLIDATION    — tight range < 0.8×ATR. Wait for breakout.
    """
    if len(closes) < 4:
        return "UNKNOWN"
    last4 = closes[-4:]
    if atr and (max(last4) - min(last4)) < atr * 0.8:
        return "CONSOLIDATION"
    up_moves   = sum(1 for i in range(-3, 0) if closes[i] > closes[i - 1])
    down_moves = sum(1 for i in range(-3, 0) if closes[i] < closes[i - 1])
    # 30-min total displacement to distinguish true spike from steady trend
    move_30m = abs(closes[-1] - closes[-6]) if len(closes) >= 6 else 0
    is_spike = bool(atr and move_30m > atr * 1.5)
    if trend_bias == "BULLISH":
        if down_moves >= 2: return "PULLBACK"
        if up_moves == 3 and is_spike: return "IMPULSE_UP"
        if up_moves >= 2: return "TRENDING_UP"
    elif trend_bias == "BEARISH":
        if up_moves >= 2: return "PULLBACK"
        if down_moves == 3 and is_spike: return "IMPULSE_DOWN"
        if down_moves >= 2: return "TRENDING_DOWN"
    return "CONSOLIDATION"


def _detect_sweep(candles: list, swing_highs: list, swing_lows: list,
                  current_price: float, atr: float):
    """
    Liquidity sweep: wick pierces a level by at least 0.3×ATR but closes back inside.
    Checks last 2 candles to catch recent sweeps.
    """
    min_pierce = atr * 0.3 if atr else 0
    for candle in reversed(candles[-2:]):
        c_high, c_low, c_close = float(candle[2]), float(candle[3]), float(candle[4])
        if swing_highs:
            nearest_res = min(swing_highs, key=lambda x: abs(x - current_price))
            if c_high > nearest_res + min_pierce and c_close < nearest_res:
                return "SWEPT_HIGHS", nearest_res
        if swing_lows:
            nearest_sup = min(swing_lows, key=lambda x: abs(x - current_price))
            if c_low < nearest_sup - min_pierce and c_close > nearest_sup:
                return "SWEPT_LOWS", nearest_sup
    return "NONE", None


# ── main price structure function ─────────────────────────────────────────────

def calculate_price_structure(candles_5m: list) -> dict:
    """
    Multi-timeframe price structure for intraday traders.

    Inputs : full session 5-min candle list.
    Outputs:
      structure_5m   — scalp timeframe (2-bar pivot, last 2 h)
      structure_15m  — swing bias (1-bar pivot on 15-min resampled bars)
      trend_strength — STRONG_BULLISH / BULLISH / WEAK_BULLISH / RANGING /
                       WEAK_BEARISH / BEARISH / STRONG_BEARISH  (weighted vote)
      trend_bias     — BULLISH / BEARISH / NEUTRAL
      phase          — IMPULSE_UP / IMPULSE_DOWN / PULLBACK / CONSOLIDATION
      bos            — BULLISH_BOS / BEARISH_BOS / None
      opening_range  — {high, low, position}  (9:15-9:30 session reference)
      last_swing_high/low, resistance_levels, support_levels
      liquidity_sweep, sweep_level
    """
    _empty = {
        "structure_5m": "UNKNOWN", "structure_15m": "UNKNOWN",
        "trend_strength": "RANGING", "trend_bias": "NEUTRAL",
        "phase": "UNKNOWN", "bos": None,
        "last_swing_high": None, "last_swing_low": None,
        "resistance_levels": [], "support_levels": [],
        "liquidity_sweep": "NONE", "sweep_level": None,
        "opening_range": None, "range_high": None, "range_low": None,
    }
    if len(candles_5m) < 5:
        return _empty

    # ── 5-min structure: use last 24 bars (2 h) ───────────────────────────────
    w5 = candles_5m[-24:] if len(candles_5m) >= 24 else candles_5m
    highs_5m  = [float(c[2]) for c in w5]
    lows_5m   = [float(c[3]) for c in w5]
    closes_5m = [float(c[4]) for c in w5]

    sh_5m, sl_5m = _find_swings(highs_5m, lows_5m, confirm=2)
    structure_5m = _structure_label(sh_5m, sl_5m)
    current_price = closes_5m[-1]

    # ── 15-min structure: resample full session → find swings ─────────────────
    w15 = _resample_to_nmin(candles_5m, 15)
    if len(w15) >= 5:
        sh_15m, sl_15m = _find_swings(
            [float(c[2]) for c in w15],
            [float(c[3]) for c in w15],
            confirm=1,          # 1-bar on 15m = 15-min confirmation each side
        )
        structure_15m = _structure_label(sh_15m, sl_15m)
    else:
        sh_15m, sl_15m = [], []
        structure_15m = "RANGING"

    # ── Opening range: first 3 five-min bars (9:15–9:30) ─────────────────────
    or_bars = candles_5m[:3]
    if or_bars:
        or_high = max(float(c[2]) for c in or_bars)
        or_low  = min(float(c[3]) for c in or_bars)
        or_pos  = ("ABOVE_OR" if current_price > or_high
                   else "BELOW_OR" if current_price < or_low
                   else "INSIDE_OR")
        opening_range = {"high": round(or_high, 2), "low": round(or_low, 2), "position": or_pos}
    else:
        opening_range = None

    # ── BOS: close beyond last confirmed swing ────────────────────────────────
    last_swing_high = sh_5m[-1] if sh_5m else max(highs_5m[:-1])
    last_swing_low  = sl_5m[-1] if sl_5m else min(lows_5m[:-1])
    prev_close = closes_5m[-2] if len(closes_5m) >= 2 else current_price

    bos = None
    if current_price > last_swing_high and prev_close <= last_swing_high:
        bos = "BULLISH_BOS"
    elif current_price < last_swing_low and prev_close >= last_swing_low:
        bos = "BEARISH_BOS"

    final_5m = bos if bos else structure_5m

    # ── ATR from 5-min window (for votes + phase + sweep filter) ────────────
    if len(closes_5m) >= 2:
        trs = [max(highs_5m[i] - lows_5m[i],
                   abs(highs_5m[i] - closes_5m[i - 1]),
                   abs(lows_5m[i]  - closes_5m[i - 1]))
               for i in range(1, len(w5))]
        atr_5m = sum(trs[-10:]) / min(10, len(trs))
    else:
        atr_5m = 0

    # ── Trend strength: weighted vote ─────────────────────────────────────────
    bull, bear = 0, 0
    if structure_15m == "BULLISH":   bull += 3
    elif structure_15m == "BEARISH": bear += 3
    if structure_5m == "BULLISH":    bull += 2
    elif structure_5m == "BEARISH":  bear += 2
    if bos == "BULLISH_BOS":         bull += 2
    elif bos == "BEARISH_BOS":       bear += 2
    if opening_range:
        if opening_range["position"] == "ABOVE_OR":   bull += 1
        elif opening_range["position"] == "BELOW_OR": bear += 1

    # ── Indicator fallback when 15m has too few bars (early-day trending) ────
    # In a clean uptrend, no bar is the highest of its neighbors → zero swings
    # → structure_15m stays RANGING even though market is clearly trending.
    # Use session displacement as additional vote to break the tie.
    if structure_15m == "RANGING" and len(closes_5m) >= 3 and atr_5m > 0:
        session_open = closes_5m[0]
        displacement = current_price - session_open
        if displacement > atr_5m * 1.5:
            bull += 2
        elif displacement > atr_5m * 0.5:
            bull += 1
        elif displacement < -atr_5m * 1.5:
            bear += 2
        elif displacement < -atr_5m * 0.5:
            bear += 1

    if bull == 0 and bear == 0:
        trend_bias, trend_strength = "NEUTRAL", "RANGING"
    elif bull > bear:
        trend_bias = "BULLISH"
        score = bull - bear
        trend_strength = "STRONG_BULLISH" if score >= 5 else ("BULLISH" if score >= 3 else "WEAK_BULLISH")
    else:
        trend_bias = "BEARISH"
        score = bear - bull
        trend_strength = "STRONG_BEARISH" if score >= 5 else ("BEARISH" if score >= 3 else "WEAK_BEARISH")

    # ── Phase ─────────────────────────────────────────────────────────────────
    phase = _detect_phase(closes_5m, trend_bias, atr_5m)

    # ── S/R: merge 5-min + 15-min swings ─────────────────────────────────────
    all_sh = sh_5m + sh_15m
    all_sl = sl_5m + sl_15m
    resistance_levels = sorted({round(h, 0) for h in all_sh if h > current_price})[:3]
    support_levels    = sorted({round(l, 0) for l in all_sl if l < current_price}, reverse=True)[:3]

    # ── Liquidity sweep ───────────────────────────────────────────────────────
    liq_sweep, sweep_level = _detect_sweep(w5, all_sh, all_sl, current_price, atr_5m)

    # ── 30-min candle summary (last 6 five-min bars) ─────────────────────────
    last6 = candles_5m[-6:] if len(candles_5m) >= 6 else candles_5m
    candles_30m_summary = {
        "open":  round(float(last6[0][1]), 2) if last6 else None,
        "high":  round(max(float(c[2]) for c in last6), 2) if last6 else None,
        "low":   round(min(float(c[3]) for c in last6), 2) if last6 else None,
        "close": round(float(last6[-1][4]), 2) if last6 else None,
        "move":  round(float(last6[-1][4]) - float(last6[0][1]), 2) if last6 else None,
        "bars":  len(last6),
    }

    return {
        "structure_5m":        final_5m,
        "structure_15m":       structure_15m,
        "trend_strength":      trend_strength,
        "trend_bias":          trend_bias,
        "phase":               phase,
        "bos":                 bos,
        "last_swing_high":     round(last_swing_high, 2),
        "last_swing_low":      round(last_swing_low, 2),
        "resistance_levels":   [round(r, 2) for r in resistance_levels],
        "support_levels":      [round(s, 2) for s in support_levels],
        "liquidity_sweep":     liq_sweep,
        "sweep_level":         round(sweep_level, 2) if sweep_level else None,
        "opening_range":       opening_range,
        "range_high":          round(max(highs_5m), 2),
        "range_low":           round(min(lows_5m), 2),
        "candles_30m_summary": candles_30m_summary,
    }


def resample_5min(candles_1m: list) -> list:
    """
    Resample 1-minute OHLCV candles into 5-minute candles.
    Each candle: [timestamp, open, high, low, close, volume, oi]
    Groups by flooring the minute to the nearest 5-min boundary.
    Returns list sorted oldest-first.
    """
    from datetime import datetime, timezone
    buckets: dict = {}
    for c in candles_1m:
        ts_raw = c[0]
        if isinstance(ts_raw, str):
            # Parse "18 June 2026 10:05:00" or ISO format
            for fmt in ("%d %B %Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(ts_raw[:19], fmt[:len(ts_raw[:19])])
                    break
                except ValueError:
                    continue
            else:
                try:
                    dt = datetime.fromisoformat(ts_raw)
                except Exception:
                    continue
        else:
            dt = ts_raw
        # Floor to 5-min boundary
        floored_min = (dt.minute // 5) * 5
        try:
            bucket_key = dt.replace(minute=floored_min, second=0, microsecond=0)
        except Exception:
            continue
        o, h, l, cl, vol = float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5]) if c[5] else 0.0
        if bucket_key not in buckets:
            buckets[bucket_key] = [bucket_key.isoformat(), o, h, l, cl, vol, 0]
        else:
            buckets[bucket_key][2] = max(buckets[bucket_key][2], h)   # high
            buckets[bucket_key][3] = min(buckets[bucket_key][3], l)   # low
            buckets[bucket_key][4] = cl                                # close = last
            buckets[bucket_key][5] += vol                              # sum volume
    return sorted(buckets.values(), key=lambda x: x[0])


def _calc_rsi(closes: list, period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 2)


def _calc_vwap(df: pd.DataFrame) -> Optional[float]:
    if df.empty:
        return None
    typical = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].replace(0, np.nan)
    if vol.notna().any():
        # Real volume available — true VWAP
        vwap = (typical * vol).cumsum() / vol.cumsum()
        val = vwap.iloc[-1]
        return round(float(val), 2) if not np.isnan(val) else None
    else:
        # Index instruments have no volume — use TWAP (session average typical price)
        return round(float(typical.mean()), 2)


def _calc_atr(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    high = df["high"]
    low  = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    return round(float(atr), 2) if not np.isnan(atr) else None
