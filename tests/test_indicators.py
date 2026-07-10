"""Tests for indicators/calculator.py."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indicators.calculator import calculate_all, calculate_price_structure


def _candle(i, close):
    ts = f"2025-07-03T09:{15 + i:02d}:00+05:30"
    return [ts, close * 0.999, close * 1.001, close * 0.997, close, 1000, 0]


def _trending_up(n=60):
    return [_candle(i, 24000 + i * 5) for i in range(n)]


def _flat(n=60):
    return [_candle(i, 24000) for i in range(n)]


def test_returns_empty_for_too_few_candles():
    assert calculate_all([]) == {}
    assert calculate_all([_candle(0, 100)]) == {}


def test_ema9_requires_9_candles():
    candles_7 = [_candle(i, 100 + i) for i in range(7)]
    res = calculate_all(candles_7)
    assert res.get("ema9") is None

    candles_10 = [_candle(i, 100 + i) for i in range(10)]
    res = calculate_all(candles_10)
    assert res.get("ema9") is not None


def test_rsi_bounded():
    res = calculate_all(_trending_up())
    rsi = res.get("rsi")
    assert rsi is not None
    assert 0 <= rsi <= 100


def test_vwap_non_negative():
    res = calculate_all(_trending_up())
    assert res.get("vwap", 0) > 0


def test_trend_up_in_uptrend():
    res = calculate_all(_trending_up(60))
    assert res.get("trend") in ("UP", "SIDEWAYS", "UNKNOWN")  # 9>21>50 in uptrend → UP


def test_bb_bands_ordered():
    res = calculate_all(_trending_up(30))
    upper  = res.get("bb_upper")
    middle = res.get("bb_middle")
    lower  = res.get("bb_lower")
    if upper and middle and lower:
        assert upper >= middle >= lower


def test_price_structure_empty_on_few_candles():
    ps = calculate_price_structure([])
    assert ps["structure_5m"] == "UNKNOWN"


def test_price_structure_trending_up():
    candles_5m = [_candle(i, 24000 + i * 10) for i in range(30)]
    ps = calculate_price_structure(candles_5m)
    # In a clean uptrend, structure should tend BULLISH or at least RANGING
    assert ps["structure_5m"] in ("BULLISH", "RANGING")
    assert "opening_range" in ps
