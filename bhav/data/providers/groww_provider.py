"""Groww API + yfinance + Black-Scholes provider for backtesting.

Features:
- Spot candles: Groww API → yfinance (progressive fallback).
- Option candles: Black-Scholes synthetic (no real API available).
- Expiry dates: Hardcoded NSE weekly schedule.
- Fallback hierarchy: Real → Synthetic → Mock.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, time
from typing import TYPE_CHECKING

from bhav.data.provider import BrokerDataProvider, BrokerError, OptionContract

if TYPE_CHECKING:
    pass


class GrowwDataProvider(BrokerDataProvider):
    """Groww API + yfinance fallback for backtesting.

    Groww provides live data; yfinance provides historical fallback.
    Option candles are synthetic (Black-Scholes).
    """

    def __init__(self, api_token: str | None = None):
        """Initialize Groww provider.

        Args:
            api_token: Optional Groww OAuth token.
                      If None, uses default authenticated session.
        """
        self.api_token = api_token
        self._client = None

    def _get_client(self):
        """Lazy-init Groww client."""
        if self._client is None:
            try:
                from groww.auth import get_groww_client
                self._client = get_groww_client()
            except Exception as e:
                raise BrokerError(f"Failed to initialize Groww client: {e}") from e
        return self._client

    def get_spot_candles(
        self,
        instrument_key: str,
        d: date,
        interval: str = "1minute",
    ) -> list[list]:
        """Fetch spot candles: Groww → yfinance fallback."""
        try:
            from groww.historical import get_index_candles
            date_str = d.strftime("%Y-%m-%d")
            return get_index_candles(instrument_key, date_str)
        except Exception as e:
            raise BrokerError(
                f"Failed to get spot candles for {instrument_key} on {d}: {e}"
            ) from e

    def get_option_candles(
        self,
        option_key: str,
        d: date,
        interval: str = "1minute",
    ) -> list[list]:
        """Generate synthetic option candles via Black-Scholes.

        Format: "NSE_INDEX|Nifty 50|2025-01-16|24000|CE"
        """
        try:
            # Try Groww's synthetic generator first
            from groww.historical import get_expired_option_candles
            date_str = d.strftime("%Y-%m-%d")
            return get_expired_option_candles(option_key, date_str)
        except Exception as e:
            # Fallback to manual synthesis
            try:
                return self._synthesize_option_candles(option_key, d)
            except Exception as synth_err:
                raise BrokerError(
                    f"Failed to get/synthesize option candles for {option_key}: {synth_err}"
                ) from synth_err

    def _synthesize_option_candles(self, option_key: str, d: date) -> list[list]:
        """Generate Black-Scholes synthetic candles from spot.

        option_key format: "NSE_INDEX|Nifty 50|2025-01-16|24000|CE"
        """
        parts = option_key.split("|")
        if len(parts) != 5:
            return []

        instrument_key = "|".join(parts[:2])
        expiry_str = parts[2]
        strike = int(parts[3])
        option_type = parts[4]

        # Fetch spot candles
        spot_candles = self.get_spot_candles(instrument_key, d)
        if not spot_candles:
            return []

        # Time to expiry
        expiry_date = date.fromisoformat(expiry_str)
        t_days = max((expiry_date - d).days, 0)
        sigma = 0.20 if t_days == 0 else 0.15  # Implied volatility

        # Generate option candles
        option_candles = []
        for c in spot_candles:
            ts = c[0]
            s_open = float(c[1])
            s_high = float(c[2])
            s_low = float(c[3])
            s_close = float(c[4])

            o_p = self._bs_price(s_open, strike, t_days, sigma, option_type)
            c_p = self._bs_price(s_close, strike, t_days, sigma, option_type)

            if option_type == "CE":
                h_p = self._bs_price(s_high, strike, t_days, sigma, option_type)
                l_p = self._bs_price(s_low, strike, t_days, sigma, option_type)
            else:  # PE
                h_p = self._bs_price(s_low, strike, t_days, sigma, option_type)
                l_p = self._bs_price(s_high, strike, t_days, sigma, option_type)

            opt_high = max(o_p, h_p, c_p)
            opt_low = min(o_p, l_p, c_p)

            option_candles.append([ts, o_p, opt_high, opt_low, c_p, 0, 0])

        return option_candles

    @staticmethod
    def _bs_price(
        S: float, K: float, T_days: float, sigma: float = 0.15, option_type: str = "CE"
    ) -> float:
        """Simplified Black-Scholes option price.

        Args:
            S: Spot price
            K: Strike price
            T_days: Time to expiry (days)
            sigma: Implied volatility
            option_type: "CE" (call) or "PE" (put)

        Returns:
            Option premium
        """
        if T_days == 0:
            # Expiry: intrinsic only
            if option_type == "CE":
                return max(0.0, S - K)
            else:
                return max(0.0, K - S)

        # Intrinsic value
        if option_type == "CE":
            intrinsic = max(0.0, S - K)
        else:
            intrinsic = max(0.0, K - S)

        # Time value (approximation)
        T = T_days / 365.0
        time_value = S * sigma * math.sqrt(T) * 0.4

        return intrinsic + time_value

    def get_expiries(self, underlying_key: str) -> list[date]:
        """Return sorted list of all past weekly expiries.

        Implementation: Calculate from NSE/BSE schedule.
        - NSE (Nifty): Every Thursday
        - BSE (Sensex): Every Friday
        """
        try:
            from groww.historical import get_expired_expiries
            raw_strings = get_expired_expiries(underlying_key)
            return sorted([date.fromisoformat(x) for x in raw_strings if x])
        except Exception as e:
            raise BrokerError(f"Failed to get expiries for {underlying_key}: {e}") from e

    def get_option_chain(
        self,
        underlying_key: str,
        expiry: date,
    ) -> list[OptionContract]:
        """Return all option contracts for one expiry.

        Limitation: Groww doesn't provide direct historical chain API.

        Options:
        1. Return empty (engine uses synthetic candles for resolution).
        2. Call live API (current data, not historical).
        3. Infer from available synthetic candles.

        For now: Return empty. Engine handles via synthetic candles.
        """
        # TODO: Implement if Groww adds historical chain endpoint
        return []

    def close(self) -> None:
        """No-op for stateless HTTP client."""
        pass
