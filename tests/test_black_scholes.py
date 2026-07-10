"""Tests for Black-Scholes option pricing in groww/pricing.py."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from groww.pricing import bs_option_price as _bs_option_price


def test_call_positive():
    price = _bs_option_price(24000, 24000, 7, 0.15, "CE")
    assert price > 0


def test_put_positive():
    price = _bs_option_price(24000, 24000, 7, 0.15, "PE")
    assert price > 0


def test_deep_itm_call():
    """Deep ITM call must be worth at least intrinsic value."""
    S, K = 25000, 24000
    price = _bs_option_price(S, K, 7, 0.15, "CE")
    intrinsic = S - K
    assert price >= intrinsic * 0.95   # allow small discount from discounting


def test_deep_otm_call_cheap():
    """Deep OTM call should be near zero (but >= minimum)."""
    price = _bs_option_price(24000, 27000, 1, 0.15, "CE")
    assert 0.05 <= price < 10   # cheap but at minimum floor


def test_call_put_parity_approx():
    """Put-call parity: C - P ≈ S - K * e^(-rT)."""
    import math
    S, K, T_days, sigma, r = 24000, 24000, 30, 0.15, 0.065
    T = T_days / 365.0
    ce = _bs_option_price(S, K, T_days, sigma, "CE")
    pe = _bs_option_price(S, K, T_days, sigma, "PE")
    # At-the-money: C - P ≈ S - K*e^(-rT)
    expected = S - K * math.exp(-r * T)
    assert abs((ce - pe) - expected) < 50   # within 50 pts


def test_zero_dte_has_minimum_price():
    """On expiry day (T=0), minimum price should be floored."""
    price = _bs_option_price(24000, 24000, 0, 0.20, "CE")
    assert price >= 0.05


def test_higher_iv_means_higher_price():
    """Higher volatility should always produce a higher option price."""
    low_iv  = _bs_option_price(24000, 24000, 7, 0.10, "CE")
    high_iv = _bs_option_price(24000, 24000, 7, 0.30, "CE")
    assert high_iv > low_iv
