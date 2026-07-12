"""
User-uploaded custom backtest strategies — safe, declarative, no code execution.

A live trading server must NEVER exec arbitrary uploaded code, so a custom
strategy is a JSON *definition* of rules over a fixed set of indicators (the same
ones indicators.calculate_all produces). The engine evaluates those rules; the
user never supplies Python.

Definition shape (all fields except name/entry_long optional):

    {
      "name": "My RSI dip",
      "time_window": ["09:45", "13:30"],        # HH:MM inclusive, optional
      "cooldown_mins": 30,                        # min gap between entries
      "entry_long":  [                            # ALL must hold -> BUY_CE
        {"field": "rsi", "op": "<", "value": 35},
        {"field": "ema9", "op": ">", "field_right": "ema21"}
      ],
      "entry_short": [                            # ALL must hold -> BUY_PE (optional)
        {"field": "rsi", "op": ">", "value": 65}
      ]
    }
"""
from __future__ import annotations

from indicators.calculator import calculate_all

# Fields a condition may reference. "close" = latest spot close; the rest come
# straight from calculate_all(). Kept as an allow-list so an upload can never
# reach into anything unexpected.
ALLOWED_FIELDS = {
    "rsi", "ema9", "ema21", "ema50", "vwap", "atr", "volume_ratio",
    "oi_change_pct", "bb_upper", "bb_middle", "bb_lower", "close",
}
ALLOWED_OPS = {">", "<", ">=", "<=", "==", "!="}
MAX_CONDITIONS = 8


class StrategyError(ValueError):
    """Raised for an invalid custom-strategy definition (safe to show the user)."""


def _time_str(candle) -> str:
    ts = str(candle[0])
    return ts[11:16] if len(ts) > 11 else ts[:5]


def _mins(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def _validate_conditions(conds, where: str) -> list[dict]:
    if not isinstance(conds, list):
        raise StrategyError(f"{where} must be a list of conditions")
    if len(conds) > MAX_CONDITIONS:
        raise StrategyError(f"{where}: at most {MAX_CONDITIONS} conditions allowed")
    out = []
    for i, c in enumerate(conds):
        if not isinstance(c, dict):
            raise StrategyError(f"{where}[{i}] must be an object")
        field = c.get("field")
        op = c.get("op")
        if field not in ALLOWED_FIELDS:
            raise StrategyError(f"{where}[{i}]: unknown field {field!r}. Allowed: {sorted(ALLOWED_FIELDS)}")
        if op not in ALLOWED_OPS:
            raise StrategyError(f"{where}[{i}]: unknown op {op!r}. Allowed: {sorted(ALLOWED_OPS)}")
        has_value = "value" in c
        has_ref = "field_right" in c
        if has_value == has_ref:
            raise StrategyError(f"{where}[{i}]: provide exactly one of 'value' or 'field_right'")
        norm = {"field": field, "op": op}
        if has_value:
            try:
                norm["value"] = float(c["value"])
            except (TypeError, ValueError):
                raise StrategyError(f"{where}[{i}]: 'value' must be a number")
        else:
            if c["field_right"] not in ALLOWED_FIELDS:
                raise StrategyError(f"{where}[{i}]: unknown field_right {c['field_right']!r}")
            norm["field_right"] = c["field_right"]
        out.append(norm)
    return out


def validate_custom(defn: dict) -> dict:
    """Validate + normalize an uploaded definition. Raises StrategyError on any
    problem, with a message safe to surface to the user."""
    if not isinstance(defn, dict):
        raise StrategyError("Strategy must be a JSON object")

    name = str(defn.get("name") or "Custom Strategy").strip()[:60]

    entry_long = _validate_conditions(defn.get("entry_long", []), "entry_long")
    entry_short = _validate_conditions(defn.get("entry_short", []), "entry_short")
    if not entry_long and not entry_short:
        raise StrategyError("Provide at least one condition in entry_long or entry_short")

    window = defn.get("time_window")
    if window is not None:
        if (not isinstance(window, (list, tuple)) or len(window) != 2):
            raise StrategyError("time_window must be [start, end] as HH:MM")
        try:
            for w in window:
                _mins(str(w))
        except Exception:
            raise StrategyError("time_window values must be HH:MM (e.g. '09:45')")
        window = [str(window[0]), str(window[1])]

    try:
        cooldown = int(defn.get("cooldown_mins", 30))
    except (TypeError, ValueError):
        raise StrategyError("cooldown_mins must be an integer")
    cooldown = max(0, min(cooldown, 375))

    return {
        "name": name,
        "entry_long": entry_long,
        "entry_short": entry_short,
        "time_window": window,
        "cooldown_mins": cooldown,
    }


def _field_value(field: str, ind: dict, close: float):
    if field == "close":
        return close
    return ind.get(field)


def _compare(left, op, right) -> bool:
    if left is None or right is None:
        return False
    if op == ">":
        return left > right
    if op == "<":
        return left < right
    if op == ">=":
        return left >= right
    if op == "<=":
        return left <= right
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    return False


def _eval_all(conds: list[dict], ind: dict, close: float) -> bool:
    for c in conds:
        left = _field_value(c["field"], ind, close)
        right = c["value"] if "value" in c else _field_value(c["field_right"], ind, close)
        if not _compare(left, c["op"], right):
            return False
    return True


def make_custom_strategy(defn: dict):
    """Return (init_fn, signal_fn) matching the strategies.py interface."""
    defn = validate_custom(defn)
    window = defn["time_window"]
    cooldown = defn["cooldown_mins"]
    entry_long = defn["entry_long"]
    entry_short = defn["entry_short"]

    def init_fn(candles_1min, prev_close: float = 0) -> dict:
        return {"last_exit_direction": None, "last_exit_time": ""}

    def signal_fn(candles_so_far: list, day_state: dict, last_trade: dict):
        if not candles_so_far:
            return None
        now = _time_str(candles_so_far[-1])
        day_state["current_time"] = now
        if window and not (window[0] <= now <= window[1]):
            return None
        last_entry = (last_trade or {}).get("entry_time", "")
        if last_entry and _mins(now) - _mins(last_entry) < cooldown:
            return None
        if len(candles_so_far) < 20:
            return None

        ind = calculate_all(candles_so_far)
        close = float(candles_so_far[-1][4])

        if entry_long and _eval_all(entry_long, ind, close):
            return "BUY_CE"
        if entry_short and _eval_all(entry_short, ind, close):
            return "BUY_PE"
        return None

    return init_fn, signal_fn
