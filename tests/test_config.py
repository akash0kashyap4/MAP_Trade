"""Tests for config.py — market calendar and trading constants."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from config import is_market_day, INSTRUMENTS, LOT_SIZES, ATM_STEP


def test_weekends_not_trading():
    assert not is_market_day(date(2025, 7, 5))   # Saturday
    assert not is_market_day(date(2025, 7, 6))   # Sunday


def test_weekdays_are_trading():
    assert is_market_day(date(2025, 7, 7))    # Monday
    assert is_market_day(date(2025, 7, 8))    # Tuesday


def test_nse_holiday_not_trading():
    # Republic Day 2026 — in the holiday list
    assert not is_market_day(date(2026, 1, 26))


def test_instruments_defined():
    assert "NIFTY" in INSTRUMENTS
    assert "BANKNIFTY" in INSTRUMENTS
    assert "SENSEX" in INSTRUMENTS


def test_lot_sizes_positive():
    for instr, size in LOT_SIZES.items():
        assert size > 0, f"{instr} lot size should be positive"


def test_atm_step():
    assert ATM_STEP == 50
