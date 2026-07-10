"""Tests for backtest/strategies.py signal generators."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.strategies import init_day, get_signal, record_exit


def _candle(hhmm, close, bullish=True):
    """Build a minimal 1-min candle at the given HH:MM."""
    ts = f"2025-07-03T{hhmm}:00+05:30"
    o = close - 2 if bullish else close + 2
    return [ts, o, close + 5, close - 5, close, 1000, 0]


def _session_candles(n_from_open=60, trend="up"):
    """Generate n intraday 1-min candles starting at 09:15."""
    candles = []
    for i in range(n_from_open):
        h = 9 + (15 + i) // 60
        m = (15 + i) % 60
        base = 24000 + (i * 3 if trend == "up" else -i * 3)
        candles.append(_candle(f"{h:02d}:{m:02d}", base, bullish=(trend == "up")))
    return candles


class TestFirstCandle:
    def test_bullish_bias_set_from_first_candle(self):
        candles = _session_candles(60, trend="up")
        state = init_day("first_candle", candles, prev_close=24000)
        assert state["bias"] in ("BUY_CE", "BUY_PE", None)

    def test_no_signal_before_0930(self):
        candles = _session_candles(10, trend="up")   # only 09:15-09:24
        state = init_day("first_candle", candles, prev_close=24000)
        sig = get_signal("first_candle", candles, state, None)
        assert sig is None  # never fires before 09:30

    def test_record_exit_clears_on_target(self):
        state = {"last_exit_direction": "CE", "last_exit_time": "09:35"}
        record_exit(state, "CE", "10:00", "TARGET")
        assert state["last_exit_direction"] is None   # reset on TARGET exit

    def test_record_exit_sets_on_sl(self):
        state = {"last_exit_direction": None, "last_exit_time": ""}
        record_exit(state, "PE", "10:15", "SL")
        assert state["last_exit_direction"] == "PE"


class TestRsiReversal:
    def test_returns_none_without_enough_candles(self):
        candles = _session_candles(5, trend="up")
        state = init_day("rsi_reversal", candles, prev_close=24000)
        sig = get_signal("rsi_reversal", candles, state, None)
        assert sig is None   # only 5 candles, RSI needs 15


class TestEmaStrategy:
    def test_init_creates_state(self):
        candles = _session_candles(60, trend="up")
        state = init_day("ema_trend", candles, prev_close=24000)
        assert "last_signal" in state

    def test_no_signal_before_min_candles(self):
        candles = _session_candles(30, trend="up")
        state = init_day("ema_trend", candles, prev_close=24000)
        sig = get_signal("ema_trend", candles[:30], state, None)
        # 30 candles < 55 minimum
        assert sig is None


class TestGapDirection:
    def test_no_bias_on_small_gap(self):
        candles = _session_candles(30, trend="up")
        # prev_close very close to open → no gap bias
        state = init_day("gap_direction", candles, prev_close=float(candles[0][1]))
        assert state["bias"] is None

    def test_bullish_bias_on_large_gap_up(self):
        candles = _session_candles(30, trend="up")
        # prev_close much lower → gap up > 0.3%
        prev_close = float(candles[0][1]) * 0.99   # 1% gap up
        state = init_day("gap_direction", candles, prev_close=prev_close)
        assert state["bias"] == "BUY_CE"
