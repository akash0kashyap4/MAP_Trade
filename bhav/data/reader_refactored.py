"""DataReader: strategies read from here. Hides provider + cache from user code.

This is the refactored version that uses BrokerDataProvider interface
instead of UpstoxClient directly.
"""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from bhav.data.cache import ParquetCache
from bhav.data.provider import BrokerDataProvider

if TYPE_CHECKING:
    pass


class DataReader:
    """Bridge between backtesting engine and data sources.

    Responsibilities:
    - Fetch candles from provider
    - Cache to disk (optional)
    - Normalize data to polars DataFrame
    """

    def __init__(self, provider: BrokerDataProvider, cache: ParquetCache | None = None) -> None:
        """Initialize reader.

        Args:
            provider: BrokerDataProvider implementation (Groww, Upstox, CSV, etc.)
            cache: Optional ParquetCache for caching candles.
        """
        self.provider = provider
        self.cache = cache

    def spot_bars(
        self, instrument_key: str, d: date, interval: str = "1minute"
    ) -> pl.DataFrame:
        """Fetch spot candles with cache-aware fallback.

        Args:
            instrument_key: Spot/index symbol (e.g., "NSE_INDEX|Nifty 50")
            d: Date to fetch
            interval: Candle interval

        Returns:
            Polars DataFrame with columns: timestamp, open, high, low, close, volume, oi
            Empty DataFrame if no data available.
        """
        # Try cache first
        if self.cache and self.cache.has(instrument_key, interval, d):
            return self.cache.read(instrument_key, interval, d)

        # Fetch from provider
        raw = self.provider.get_spot_candles(instrument_key, d, interval)
        if not raw:
            return pl.DataFrame()

        # Convert to DataFrame
        df = self.cache.candles_to_frame(raw) if self.cache else self._candles_to_frame(raw)

        # Cache for next time
        if self.cache and not df.is_empty():
            self.cache.write(instrument_key, interval, d, df)

        return df

    def option_bars(
        self, option_key: str, d: date, interval: str = "1minute"
    ) -> pl.DataFrame:
        """Fetch option candles with cache-aware fallback.

        Args:
            option_key: Option identifier (broker-specific)
            d: Date to fetch
            interval: Candle interval

        Returns:
            Polars DataFrame with columns: timestamp, open, high, low, close, volume, oi
            Empty DataFrame if no data or synthetic unavailable.
        """
        # Try cache first
        if self.cache and self.cache.has(option_key, interval, d):
            return self.cache.read(option_key, interval, d)

        # Fetch from provider (real or synthetic)
        raw = self.provider.get_option_candles(option_key, d, interval)
        if not raw:
            return pl.DataFrame()

        # Convert to DataFrame
        df = self.cache.candles_to_frame(raw) if self.cache else self._candles_to_frame(raw)

        # Cache for next time
        if self.cache and not df.is_empty():
            self.cache.write(option_key, interval, d, df)

        return df

    def expiries(self, underlying_key: str) -> list[date]:
        """Fetch all past expiry dates for an underlying.

        Args:
            underlying_key: Spot/index symbol

        Returns:
            Sorted list of expiry dates (oldest first)
        """
        return self.provider.get_expiries(underlying_key)

    def option_chain(self, underlying_key: str, expiry: date):
        """Fetch option chain for one expiry.

        Args:
            underlying_key: Spot/index symbol
            expiry: Expiry date

        Returns:
            List of OptionContract objects
        """
        return self.provider.get_option_chain(underlying_key, expiry)

    @staticmethod
    def _candles_to_frame(raw_candles: list[list]) -> pl.DataFrame:
        """Convert raw candle list to Polars DataFrame.

        Input format: [[timestamp, open, high, low, close, volume, oi], ...]
        """
        if not raw_candles:
            return pl.DataFrame()

        return pl.DataFrame(
            raw_candles,
            schema=["timestamp", "open", "high", "low", "close", "volume", "oi"],
            orient="row",
        ).with_columns(
            pl.col("timestamp").str.to_datetime("%Y-%m-%dT%H:%M:%S%z")
        )
