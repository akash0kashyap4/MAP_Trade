"""
Pure-math option pricing utilities — no external dependencies.
Used by historical.py for Black-Scholes synthetic option candle generation.
"""
from __future__ import annotations
import math


def bs_option_price(S: float, K: float, T_days: float,
                    sigma: float = 0.15, option_type: str = "CE") -> float:
    """
    Black-Scholes option price using Abramowitz & Stegun normal CDF approximation.
    No scipy dependency — pure Python math module only.

    Args:
        S: spot price
        K: strike price
        T_days: days to expiry
        sigma: implied volatility (annualised fraction, e.g. 0.15 = 15%)
        option_type: "CE" (call) or "PE" (put)

    Returns:
        Option price in same units as S/K, floored at 0.05.
    """
    T = max(T_days / 365.0, 1 / 365.0)
    r = 0.065  # India risk-free rate ~6.5%

    def _ncdf(x: float) -> float:
        """Cumulative standard normal distribution (Abramowitz & Stegun)."""
        k = 1.0 / (1.0 + 0.2316419 * abs(x))
        p = 0.3989422803 * math.exp(-0.5 * x * x)
        poly = k * (0.319381530 + k * (-0.356563782 + k * (
            1.781477937 + k * (-1.821255978 + k * 1.330274429))))
        cdf = 1.0 - p * poly
        return cdf if x >= 0 else 1.0 - cdf

    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        if option_type == "CE":
            price = S * _ncdf(d1) - K * math.exp(-r * T) * _ncdf(d2)
        else:
            price = K * math.exp(-r * T) * _ncdf(-d2) - S * _ncdf(-d1)
        return max(round(price, 2), 0.05)
    except (ValueError, ZeroDivisionError):
        return 1.0
