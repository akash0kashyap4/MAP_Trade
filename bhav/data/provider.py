"""Abstract interface for broker/data providers.

Implementations handle provider-specific auth, API calls, and fallbacks.
The engine uses only this interface—it's broker-agnostic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Optional


class BrokerError(Exception):
    """Base exception for any broker/data provider failure."""
    pass


@dataclass(frozen=True)
class OptionContract:
    """Immutable option contract metadata."""

    instrument_key: str  # Broker's unique ID (e.g., "NSE_FO|Nifty50-01Jan2025-24000CE")
    strike: int          # Strike price
    option_type: str     # "CE" or "PE"
    expiry: date         # Expiry date


class BrokerDataProvider(ABC):
    """Abstract interface for historical data access.

    Implementations: GrowwDataProvider, UpstoxProvider, LocalCsvProvider, etc.

    Contract:
    - All methods return data in normalized format (list of lists).
    - Timestamps in ISO format with IST timezone (YYYY-MM-DDTHH:MM:SS+05:30).
    - Prices as floats, volumes as ints, OI as ints.
    - Return empty list on "no data available" (never None).
    - All exceptions wrapped in BrokerError for consistent error handling.
    - Methods are idempotent and thread-safe (or clearly document if not).
    """

    @abstractmethod
    def get_spot_candles(
        self,
        instrument_key: str,
        d: date,
        interval: str = "1minute",
    ) -> list[list]:
        """Fetch OHLCV candles for spot/index on one trading day.

        Args:
            instrument_key: Broker's symbol (e.g., "NSE_INDEX|Nifty 50").
            d: Date to fetch.
            interval: Candle interval ("1minute", "5minute", "1hour", etc.).

        Returns:
            List of candles: [[timestamp, open, high, low, close, volume, oi], ...]
            Empty list if no data available.

        Raises:
            BrokerError: On non-recoverable API or data errors.
        """
        pass

    @abstractmethod
    def get_option_candles(
        self,
        option_key: str,
        d: date,
        interval: str = "1minute",
    ) -> list[list]:
        """Fetch OHLCV candles for one option contract on one trading day.

        Args:
            option_key: Broker-specific option identifier.
                       Format varies by broker:
                       - Upstox: "NSE_FO|Nifty50-01Jan2025-24000CE"
                       - Groww: "NSE_FO|Nifty50|2025-01-01|24000|CE"
            d: Date to fetch.
            interval: Candle interval ("1minute", "5minute", etc.).

        Returns:
            List of candles: [[timestamp, open, high, low, close, volume, oi], ...]
            Empty list if no data or synthetic generation failed.

        Notes:
            - Can be real historical candles (preferred) or synthetic.
            - Synthetic: Generated via Black-Scholes or other models.
            - Some brokers only provide synthetic; acceptable for backtesting.

        Raises:
            BrokerError: On non-recoverable API or generation errors.
        """
        pass

    @abstractmethod
    def get_expiries(self, underlying_key: str) -> list[date]:
        """Return list of all past expiry dates for an underlying.

        Args:
            underlying_key: Spot/index symbol (e.g., "NSE_INDEX|Nifty 50").

        Returns:
            Sorted list of date objects (oldest first).
            Empty list if no expiries available.

        Raises:
            BrokerError: On non-recoverable API errors.
        """
        pass

    @abstractmethod
    def get_option_chain(
        self,
        underlying_key: str,
        expiry: date,
    ) -> list[OptionContract]:
        """Return all option contracts (CE + PE, all strikes) for one expiry.

        Args:
            underlying_key: Spot/index symbol (e.g., "NSE_INDEX|Nifty 50").
            expiry: Expiry date.

        Returns:
            List of OptionContract (all strikes and types for this expiry).
            Empty list if expiry not available or API doesn't support chains.

        Notes:
            - If broker doesn't provide historical chains, return empty list.
            - Engine can still backtest using synthetic candles + strike resolution.

        Raises:
            BrokerError: On non-recoverable API errors.
        """
        pass

    def close(self) -> None:
        """Optional cleanup: close HTTP connections, release resources.

        Implementations should tolerate multiple calls.
        """
        pass

    def __enter__(self) -> BrokerDataProvider:
        """Context manager entry."""
        return self

    def __exit__(self, *args: object) -> None:
        """Context manager exit; calls close()."""
        self.close()
