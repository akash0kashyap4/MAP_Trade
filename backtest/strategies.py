"""
Rule-based backtest strategies — multi-trade, 5-minute resolution.
v2: Smarter re-entries — trend confirmation required on every entry,
    no re-entry in same direction after SL without a reversal signal first.

Each strategy exposes:
  init_day(candles_1min, prev_close) → day_state dict
  get_signal(candles_so_far, day_state, last_trade) → "BUY_CE" | "BUY_PE" | None

day_state keys used across strategies:
  last_exit_direction : "CE" | "PE" | None  — direction of last SL exit
  last_exit_time      : "HH:MM" | ""
  trades_today        : int
"""
from __future__ import annotations
from indicators.calculator import calculate_all


STRATEGIES = {
    "first_candle":  "First Candle Direction",
    "orb15":         "Opening Range Breakout (15 min)",
    "rsi_reversal":  "RSI Reversal (30 min)",
    "ema_trend":     "EMA Trend Follow (9/21/50)",
    "gap_direction": "Gap & Go (open vs prev close)",
}

COOLDOWN_MINS  = 30    # min gap between two entries
MAX_TRADES_DAY = 2     # hard cap per strategy per day


def _time_str(candle) -> str:
    ts = str(candle[0])
    return ts[11:16] if len(ts) > 11 else ts[:5]


def _mins(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def _cooldown_ok(last_time: str, now: str, mins: int = COOLDOWN_MINS) -> bool:
    if not last_time:
        return True
    return _mins(now) - _mins(last_time) >= mins


def _candles_between(candles, start_hhmm, end_hhmm):
    return [c for c in candles if start_hhmm <= _time_str(c) <= end_hhmm]


def _ema_trend(candles) -> str:
    """Returns 'BULL', 'BEAR', or 'FLAT' based on EMA9/21 alignment."""
    if len(candles) < 25:
        return "FLAT"
    ind = calculate_all(candles[-60:])
    e9, e21 = ind.get("ema9"), ind.get("ema21")
    if e9 is None or e21 is None:
        return "FLAT"
    spread = abs(e9 - e21) / e21 * 100
    if spread < 0.05:      # EMAs too close — chop
        return "FLAT"
    if e9 > e21:
        return "BULL"
    return "BEAR"


def _rsi(candles) -> float | None:
    if len(candles) < 15:
        return None
    return calculate_all(candles[-30:]).get("rsi")


def _same_direction_after_sl(day_state: dict, direction: str) -> bool:
    """True if we're trying to re-enter the same direction that just got stopped out."""
    last_exit = day_state.get("last_exit_direction")
    last_exit_time = day_state.get("last_exit_time", "")
    now = day_state.get("current_time", "")
    if not last_exit or last_exit != direction:
        return False
    # Block same-direction re-entry for 45 min after SL
    if last_exit_time and now and _mins(now) - _mins(last_exit_time) < 45:
        return True
    return False


# ── Strategy 1: First Candle Direction ───────────────────────────────────────
def first_candle_init(candles_1min: list, prev_close: float = 0) -> dict:
    orb = _candles_between(candles_1min, "09:15", "09:29")
    bias = None
    if orb:
        c = orb[0]
        o, cl = float(c[1]), float(c[4])
        if cl > o:
            bias = "BUY_CE"
        elif cl < o:
            bias = "BUY_PE"
    return {"bias": bias, "last_exit_direction": None, "last_exit_time": ""}


def first_candle_signal(candles_so_far: list, day_state: dict, last_trade: dict) -> str | None:
    bias = day_state.get("bias")
    if not bias:
        return None
    now = _time_str(candles_so_far[-1])
    day_state["current_time"] = now
    if not ("09:30" <= now <= "14:00"):
        return None
    last_entry = last_trade.get("entry_time", "") if last_trade else ""
    if not _cooldown_ok(last_entry, now):
        return None
    direction = "CE" if bias == "BUY_CE" else "PE"
    if _same_direction_after_sl(day_state, direction):
        return None
    # Require EMA to confirm bias
    trend = _ema_trend(candles_so_far)
    if bias == "BUY_CE" and trend == "BULL":
        return "BUY_CE"
    if bias == "BUY_PE" and trend == "BEAR":
        return "BUY_PE"
    return None


# ── Strategy 2: ORB 15-min ───────────────────────────────────────────────────
def orb15_init(candles_1min: list, prev_close: float = 0) -> dict:
    orb = _candles_between(candles_1min, "09:15", "09:29")
    if len(orb) < 3:
        return {"orb_high": None, "orb_low": None,
                "last_exit_direction": None, "last_exit_time": ""}
    return {
        "orb_high": max(float(c[2]) for c in orb),
        "orb_low":  min(float(c[3]) for c in orb),
        "last_exit_direction": None,
        "last_exit_time": "",
    }


def orb15_signal(candles_so_far: list, day_state: dict, last_trade: dict) -> str | None:
    orb_high = day_state.get("orb_high")
    orb_low  = day_state.get("orb_low")
    if orb_high is None or orb_low is None:
        return None
    # ORB is a one-shot morning strategy — only one trade per day
    if last_trade:
        return None
    now = _time_str(candles_so_far[-1])
    day_state["current_time"] = now
    if not ("09:30" <= now <= "10:30"):
        return None

    last_close = float(candles_so_far[-1][4])

    if last_close > orb_high:
        return "BUY_CE"

    if last_close < orb_low:
        return "BUY_PE"

    return None


# ── Strategy 3: RSI Reversal ─────────────────────────────────────────────────
def rsi_reversal_init(candles_1min: list, prev_close: float = 0) -> dict:
    return {"last_exit_direction": None, "last_exit_time": ""}


def rsi_reversal_signal(candles_so_far: list, day_state: dict, last_trade: dict) -> str | None:
    now = _time_str(candles_so_far[-1])
    day_state["current_time"] = now

    # Skip Thursday — expiry-day premium behaviour is erratic (33% win rate vs 62%+ other days)
    ts = str(candles_so_far[-1][0])
    from datetime import datetime
    try:
        dow = datetime.fromisoformat(ts[:10]).weekday()  # 0=Mon … 3=Thu … 4=Fri
    except Exception:
        dow = -1
    if dow == 3:
        return None

    # Only trade 10:00–13:30; pre-10:00 win rate is 37.5% vs 61–67% later
    if not ("10:00" <= now <= "13:30"):
        return None

    last_entry = last_trade.get("entry_time", "") if last_trade else ""
    if not _cooldown_ok(last_entry, now, mins=45):
        return None

    rsi = _rsi(candles_so_far)
    if rsi is None:
        return None

    trend = _ema_trend(candles_so_far)

    # RSI oversold + EMA bullish (or neutral) = buy CE
    if rsi < 35 and trend != "BEAR":
        if not _same_direction_after_sl(day_state, "CE"):
            return "BUY_CE"

    # RSI overbought + EMA bearish (or neutral) = buy PE
    if rsi > 65 and trend != "BULL":
        if not _same_direction_after_sl(day_state, "PE"):
            return "BUY_PE"

    return None


# ── Strategy 4: EMA Trend Follow ─────────────────────────────────────────────
def ema_trend_init(candles_1min: list, prev_close: float = 0) -> dict:
    return {"last_signal": None, "last_exit_direction": None, "last_exit_time": ""}


def ema_trend_signal(candles_so_far: list, day_state: dict, last_trade: dict) -> str | None:
    now = _time_str(candles_so_far[-1])
    day_state["current_time"] = now
    if not ("09:45" <= now <= "13:30"):
        return None
    last_entry = last_trade.get("entry_time", "") if last_trade else ""
    if not _cooldown_ok(last_entry, now, mins=45):
        return None
    if len(candles_so_far) < 55:
        return None

    ind = calculate_all(candles_so_far)
    e9, e21, e50 = ind.get("ema9"), ind.get("ema21"), ind.get("ema50")
    if None in (e9, e21, e50):
        return None

    # Require full stack alignment (strict)
    signal = None
    if e9 > e21 > e50:
        signal = "BUY_CE"
    elif e9 < e21 < e50:
        signal = "BUY_PE"

    if not signal:
        return None

    # Only fire on a new alignment
    if signal == day_state.get("last_signal"):
        return None

    direction = "CE" if signal == "BUY_CE" else "PE"
    if _same_direction_after_sl(day_state, direction):
        return None

    # Extra: require RSI to confirm (not overbought on CE entry, not oversold on PE)
    rsi = _rsi(candles_so_far)
    if rsi is not None:
        if signal == "BUY_CE" and rsi > 70:
            return None
        if signal == "BUY_PE" and rsi < 30:
            return None

    day_state["last_signal"] = signal
    return signal


# ── Strategy 5: Gap & Go ──────────────────────────────────────────────────────
def gap_direction_init(candles_1min: list, prev_close: float = 0) -> dict:
    bias = None
    if candles_1min and prev_close > 0:
        open_price = float(candles_1min[0][1])
        gap_pct = (open_price - prev_close) / prev_close * 100
        if gap_pct > 0.3:
            bias = "BUY_CE"
        elif gap_pct < -0.3:
            bias = "BUY_PE"
    return {"bias": bias, "last_exit_direction": None, "last_exit_time": ""}


def gap_direction_signal(candles_so_far: list, day_state: dict, last_trade: dict) -> str | None:
    bias = day_state.get("bias")
    if not bias:
        return None
    now = _time_str(candles_so_far[-1])
    day_state["current_time"] = now
    if not ("09:30" <= now <= "13:30"):
        return None
    last_entry = last_trade.get("entry_time", "") if last_trade else ""
    if not _cooldown_ok(last_entry, now):
        return None

    direction = "CE" if bias == "BUY_CE" else "PE"
    if _same_direction_after_sl(day_state, direction):
        return None

    # Require EMA to agree with gap direction
    trend = _ema_trend(candles_so_far)
    trend_ok = (bias == "BUY_CE" and trend == "BULL") or (bias == "BUY_PE" and trend == "BEAR")
    if not trend_ok:
        return None

    # Enter when price pulls back to within 0.3% of VWAP
    ind = calculate_all(candles_so_far)
    vwap = ind.get("vwap")
    if not vwap:
        return None
    last_close = float(candles_so_far[-1][4])
    if abs(last_close - vwap) / vwap * 100 <= 0.3:
        return bias
    return None


# ── Public interface ─────────────────────────────────────────────────────────

_INIT_MAP = {
    "first_candle":  first_candle_init,
    "orb15":         orb15_init,
    "rsi_reversal":  rsi_reversal_init,
    "ema_trend":     ema_trend_init,
    "gap_direction": gap_direction_init,
}

_SIGNAL_MAP = {
    "first_candle":  first_candle_signal,
    "orb15":         orb15_signal,
    "rsi_reversal":  rsi_reversal_signal,
    "ema_trend":     ema_trend_signal,
    "gap_direction": gap_direction_signal,
}


def register_custom(defn: dict) -> str:
    """Register an uploaded declarative strategy under the key 'custom' so the
    engine can run it by name. Returns its display name. Single-user, single
    backtest-at-a-time deployment, so overwriting the 'custom' slot is fine."""
    from backtest.custom_strategy import make_custom_strategy
    init_fn, signal_fn = make_custom_strategy(defn)
    _INIT_MAP["custom"] = init_fn
    _SIGNAL_MAP["custom"] = signal_fn
    name = defn.get("name") or "Custom Strategy"
    STRATEGIES["custom"] = name
    return name


def init_day(strategy: str, candles_1min: list, prev_close: float = 0) -> dict:
    fn = _INIT_MAP.get(strategy)
    return fn(candles_1min, prev_close) if fn else {}


def get_signal(strategy: str, candles_so_far: list, day_state: dict,
               last_trade: dict = None) -> str | None:
    fn = _SIGNAL_MAP.get(strategy)
    return fn(candles_so_far, day_state, last_trade or {}) if fn else None


def record_exit(day_state: dict, exit_direction: str, exit_time: str, exit_reason: str):
    """Call this after each trade exits so strategies can update their state."""
    if exit_reason == "SL":
        day_state["last_exit_direction"] = exit_direction
        day_state["last_exit_time"]      = exit_time
    else:
        # On TARGET or EOD exit, reset the SL block — market proved the direction
        day_state["last_exit_direction"] = None
        day_state["last_exit_time"]      = ""
