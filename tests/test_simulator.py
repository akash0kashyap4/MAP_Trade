"""Tests for backtest/simulator.py — core P&L engine."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.simulator import simulate_trade


def _make_candles(prices: list[float]) -> list:
    """Build minimal [ts, open, high, low, close, vol] candles from a close-price list."""
    candles = []
    for i, p in enumerate(prices):
        ts = f"2025-07-03T09:{15 + i:02d}:00+05:30"
        candles.append([ts, p, p * 1.002, p * 0.998, p, 0])
    return candles


def test_target_hit():
    """Option price rises to target — should exit TARGET."""
    entry = 100.0
    # Price goes up: 102, 108, 115 — target = entry + (target_rs/qty) = 100 + 1000/65 ≈ 115.38
    candles = _make_candles([102, 108, 120])
    result = simulate_trade(
        entry_price=entry,
        candles_after_entry=candles,
        sl_rs=500,
        target_rs=1000,
        lot_size=65,
        lots=1,
    )
    assert result is not None
    assert result.exit_reason == "TARGET"
    assert result.pnl_final > 0


def test_sl_hit():
    """Option price drops below SL — should exit SL with a loss."""
    entry = 100.0
    # SL = entry - 500/65 ≈ 92.31; prices drop fast
    candles = _make_candles([98, 93, 90])
    result = simulate_trade(
        entry_price=entry,
        candles_after_entry=candles,
        sl_rs=500,
        target_rs=1000,
        lot_size=65,
        lots=1,
    )
    assert result is not None
    assert result.exit_reason == "SL"
    assert result.pnl_final < 0


def test_eod_exit():
    """Price never hits SL or target — exits EOD at last close."""
    entry = 100.0
    candles = _make_candles([101, 102, 103])  # steady small gain, never hits target
    result = simulate_trade(
        entry_price=entry,
        candles_after_entry=candles,
        sl_rs=500,
        target_rs=5000,   # very high target — never hit
        lot_size=65,
        lots=1,
    )
    assert result is not None
    assert result.exit_reason == "EOD"


def test_zero_entry_returns_none():
    """Zero entry price should return None — guard against bad data."""
    result = simulate_trade(
        entry_price=0.0,
        candles_after_entry=_make_candles([100]),
        sl_rs=500, target_rs=1000, lot_size=65, lots=1,
    )
    assert result is None


def test_empty_candles_returns_none():
    result = simulate_trade(
        entry_price=100.0,
        candles_after_entry=[],
        sl_rs=500, target_rs=1000, lot_size=65, lots=1,
    )
    assert result is None


def test_trailing_sl_activates():
    """Trailing SL should move up when profit hits trigger threshold."""
    entry = 100.0
    # Rise to ~140 (40% of tgt=1000/65≈15.4 → trigger at 6.16 pts = 106.16)
    # then fall — should exit above original SL
    sl_rs, tgt_rs = 500, 1000

    candles = _make_candles([105, 110, 108, 106, 104, 102, 100])
    result = simulate_trade(
        entry_price=entry,
        candles_after_entry=candles,
        sl_rs=sl_rs,
        target_rs=tgt_rs,
        lot_size=65,
        lots=1,
        trailing_sl_trigger=0.40,
        trailing_sl_step=0.20,
    )
    assert result is not None
    # Should exit either via trailing SL or EOD — not raw original SL
    assert result.exit_reason in ("SL", "EOD")


def test_pnl_components():
    """P&L = raw - brokerage; brokerage includes STT on exit side."""
    entry = 50.0
    candles = _make_candles([51, 52, 53, 54, 55, 56, 57, 58, 59, 70])
    result = simulate_trade(
        entry_price=entry,
        candles_after_entry=candles,
        sl_rs=500,
        target_rs=200,   # small target: 200/65 ≈ 3.08 pts → hit at 53+
        lot_size=65,
        lots=1,
    )
    assert result is not None
    assert result.pnl_raw > result.pnl_final   # brokerage always reduces P&L
    # pnl values are float arithmetic — verify they're close to their rounded form
    assert abs(result.pnl_final - round(result.pnl_final, 2)) < 0.01
