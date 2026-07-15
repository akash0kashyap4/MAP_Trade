"""Instrument resolver: (date, spot, option_type) → instrument_key.

Refactored to use BrokerDataProvider instead of UpstoxClient.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from bhav.data.provider import BrokerDataProvider, OptionContract
from bhav.data.underlyings import default_atm_step


@dataclass(frozen=True)
class ResolvedOption:
    """Resolved option contract with adjustment flag."""

    contract: OptionContract
    adjusted: bool  # True if fallback strike was used


class InstrumentResolver:
    """Handles expiry selection, ATM rounding, strike-not-found fallback.

    Now provider-agnostic: works with any BrokerDataProvider.
    """

    def __init__(
        self,
        provider: BrokerDataProvider,
        underlying_key: str,
        *,
        atm_step: int | None = None,
        fallback_offsets: tuple[int, ...] = (1, -1, 2, -2),
    ) -> None:
        """Initialize resolver.

        Args:
            provider: BrokerDataProvider (Groww, Upstox, CSV, etc.)
            underlying_key: Spot/index symbol
            atm_step: ATM rounding step (auto-lookup if None)
            fallback_offsets: Strikes to try if exact not found
        """
        self.provider = provider
        self.underlying_key = underlying_key
        self.atm_step = atm_step if atm_step is not None else default_atm_step(underlying_key)
        self.fallback_offsets = fallback_offsets
        self._expiries: list[date] | None = None
        self._chain_cache: dict[date, dict[tuple[int, str], OptionContract]] = {}

    def expiries(self) -> list[date]:
        """Fetch all past expiry dates (cached)."""
        if self._expiries is None:
            self._expiries = self.provider.get_expiries(self.underlying_key)
        return self._expiries

    def nearest_expiry(self, on_date: date, kind: str = "weekly") -> date | None:
        """Find nearest expiry on or after on_date.

        Args:
            on_date: Reference date
            kind: Expiry type ("weekly" for now)

        Returns:
            Nearest expiry date or None if none available
        """
        candidates = [e for e in self.expiries() if e >= on_date]
        if not candidates:
            return None
        return min(candidates)

    def atm_strike(self, spot: float) -> int:
        """Round spot price to ATM strike."""
        return int(round(spot / self.atm_step) * self.atm_step)

    def _chain(self, expiry: date) -> dict[tuple[int, str], OptionContract]:
        """Fetch option chain for expiry (cached)."""
        if expiry not in self._chain_cache:
            contracts = self.provider.get_option_chain(self.underlying_key, expiry)
            self._chain_cache[expiry] = {(c.strike, c.option_type): c for c in contracts}
        return self._chain_cache[expiry]

    def resolve(
        self, expiry: date, strike: int, option_type: str, on_date: date | None = None
    ) -> ResolvedOption | None:
        """Resolve exact or nearby strike.

        Tries:
        1. Exact strike
        2. Fallback strikes (offset by atm_step)

        Args:
            expiry: Option expiry date
            strike: Desired strike
            option_type: "CE" or "PE"
            on_date: Optional reference date (for interface parity)

        Returns:
            ResolvedOption or None if no contract found
        """
        chain = self._chain(expiry)
        key = (strike, option_type)

        # Try exact strike
        if key in chain:
            return ResolvedOption(contract=chain[key], adjusted=False)

        # Try fallback strikes
        for offset in self.fallback_offsets:
            k = (strike + offset * self.atm_step, option_type)
            if k in chain:
                return ResolvedOption(contract=chain[k], adjusted=True)

        return None
