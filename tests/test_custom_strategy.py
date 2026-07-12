"""Tests for user-uploaded declarative backtest strategies."""
import pytest

from backtest.custom_strategy import (
    StrategyError, make_custom_strategy, validate_custom,
)


def _candles(close, n=30, rsi_seed=None):
    # minimal OHLCV rows [time, o, h, l, c, v] with a HH:MM:SS timestamp at 10:00
    rows = []
    for i in range(n):
        rows.append([f"2025-01-15T10:{i % 60:02d}:00", close, close + 5, close - 5, close, 1000])
    return rows


# ── validation ────────────────────────────────────────────────────────────────

def test_valid_definition_normalizes():
    d = validate_custom({
        "name": "x" * 200,
        "entry_long": [{"field": "rsi", "op": "<", "value": 35}],
        "cooldown_mins": 9999,
    })
    assert len(d["name"]) <= 60
    assert d["cooldown_mins"] == 375           # clamped
    assert d["entry_long"][0]["value"] == 35.0


def test_rejects_unknown_field():
    with pytest.raises(StrategyError):
        validate_custom({"entry_long": [{"field": "wibble", "op": "<", "value": 1}]})


def test_rejects_unknown_op():
    with pytest.raises(StrategyError):
        validate_custom({"entry_long": [{"field": "rsi", "op": "≈", "value": 1}]})


def test_rejects_both_value_and_field_right():
    with pytest.raises(StrategyError):
        validate_custom({"entry_long": [
            {"field": "rsi", "op": "<", "value": 1, "field_right": "ema9"}]})


def test_requires_at_least_one_condition():
    with pytest.raises(StrategyError):
        validate_custom({"name": "empty", "entry_long": [], "entry_short": []})


def test_rejects_bad_time_window():
    with pytest.raises(StrategyError):
        validate_custom({"entry_long": [{"field": "rsi", "op": "<", "value": 1}],
                         "time_window": ["9am", "5pm"]})


def test_rejects_non_object():
    with pytest.raises(StrategyError):
        validate_custom(["not", "a", "dict"])


# ── signal evaluation ──────────────────────────────────────────────────────────

def test_signal_fires_long_when_condition_met(monkeypatch):
    # Force indicators so the condition (rsi < 35 AND ema9 > ema21) is true.
    import backtest.custom_strategy as cs
    monkeypatch.setattr(cs, "calculate_all",
                        lambda c: {"rsi": 20, "ema9": 100, "ema21": 90})
    init, signal = make_custom_strategy({
        "name": "dip",
        "entry_long": [
            {"field": "rsi", "op": "<", "value": 35},
            {"field": "ema9", "op": ">", "field_right": "ema21"},
        ],
    })
    state = init(_candles(100))
    assert signal(_candles(100), state, {}) == "BUY_CE"


def test_signal_none_when_condition_not_met(monkeypatch):
    import backtest.custom_strategy as cs
    monkeypatch.setattr(cs, "calculate_all", lambda c: {"rsi": 55, "ema9": 100, "ema21": 90})
    init, signal = make_custom_strategy({
        "entry_long": [{"field": "rsi", "op": "<", "value": 35}],
    })
    assert signal(_candles(100), init(_candles(100)), {}) is None


def test_signal_short_fires(monkeypatch):
    import backtest.custom_strategy as cs
    monkeypatch.setattr(cs, "calculate_all", lambda c: {"rsi": 75})
    init, signal = make_custom_strategy({
        "entry_short": [{"field": "rsi", "op": ">", "value": 68}],
    })
    assert signal(_candles(100), init(_candles(100)), {}) == "BUY_PE"


def test_time_window_blocks_outside_hours(monkeypatch):
    import backtest.custom_strategy as cs
    monkeypatch.setattr(cs, "calculate_all", lambda c: {"rsi": 20})
    init, signal = make_custom_strategy({
        "entry_long": [{"field": "rsi", "op": "<", "value": 35}],
        "time_window": ["13:00", "14:00"],   # candles are at 10:xx -> blocked
    })
    assert signal(_candles(100), init(_candles(100)), {}) is None


def test_cooldown_blocks_recent_reentry(monkeypatch):
    import backtest.custom_strategy as cs
    monkeypatch.setattr(cs, "calculate_all", lambda c: {"rsi": 20})
    init, signal = make_custom_strategy({
        "entry_long": [{"field": "rsi", "op": "<", "value": 35}],
        "cooldown_mins": 30,
    })
    # last entry at 10:20, current candle 10:29 -> within cooldown
    rows = [[f"2025-01-15T10:{i:02d}:00", 100, 105, 95, 100, 1000] for i in range(30)]
    assert signal(rows, init(rows), {"entry_time": "10:20"}) is None


def test_none_indicator_value_is_safe(monkeypatch):
    import backtest.custom_strategy as cs
    monkeypatch.setattr(cs, "calculate_all", lambda c: {"rsi": None})
    init, signal = make_custom_strategy({
        "entry_long": [{"field": "rsi", "op": "<", "value": 35}],
    })
    assert signal(_candles(100), init(_candles(100)), {}) is None
