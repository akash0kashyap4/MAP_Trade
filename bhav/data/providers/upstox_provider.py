"""Upstox API provider (backward compatibility wrapper).

Wraps the existing UpstoxClient to implement BrokerDataProvider interface.
Allows gradual migration from Upstox to other brokers.
"""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from bhav.data.provider import BrokerDataProvider, BrokerError, OptionContract
from bhav.data.upstox_client import UpstoxClient, UpstoxError, TokenExpiredError

if TYPE_CHECKING:
    pass


class UpstoxProvider(BrokerDataProvider):
    """Upstox API provider wrapper.

    Implements BrokerDataProvider interface using existing UpstoxClient.
    Provides backward compatibility and allows parallel operation with new providers.
    """

    def __init__(
        self,
        token: str,
        *,
        timeout: float = 15.0,
        retries: int = 3,
        backoff: float = 0.5,
    ):
        """Initialize Upstox provider.

        Args:
            token: Upstox API access token (required).
            timeout: HTTP request timeout (seconds).
            retries: Number of retry attempts on transient failures.
            backoff: Initial backoff delay (seconds) for exponential retry.
        """
        try:
            self._client = UpstoxClient(
                token=token,
                timeout=timeout,
                retries=retries,
                backoff=backoff,
            )
        except UpstoxError as e:
            raise BrokerError(f"Failed to initialize Upstox client: {e}") from e

    def get_spot_candles(
        self,
        instrument_key: str,
        d: date,
        interval: str = "1minute",
    ) -> list[list]:
        """Fetch spot candles via Upstox historical endpoint."""
        try:
            raw_candles = self._client.get_index_candles(instrument_key, interval, d, d)
            # Normalize to standard format: [timestamp, open, high, low, close, volume, oi]
            return raw_candles
        except TokenExpiredError as e:
            raise BrokerError(f"Upstox token expired: {e}") from e
        except UpstoxError as e:
            raise BrokerError(f"Failed to get spot candles from Upstox: {e}") from e

    def get_option_candles(
        self,
        option_key: str,
        d: date,
        interval: str = "1minute",
    ) -> list[list]:
        """Fetch option candles via Upstox expired-instruments endpoint.

        Args:
            option_key: Upstox instrument key format (e.g., "NSE_FO|Nifty50-01Jan2025-24000CE")
            d: Date to fetch
            interval: Candle interval
        """
        try:
            raw_candles = self._client.get_expired_option_candles(
                option_key, interval, d, d
            )
            return raw_candles
        except TokenExpiredError as e:
            raise BrokerError(f"Upstox token expired: {e}") from e
        except UpstoxError as e:
            raise BrokerError(f"Failed to get option candles from Upstox: {e}") from e

    def get_expiries(self, underlying_key: str) -> list[date]:
        """Fetch past expiry dates from Upstox."""
        try:
            raw_dates = self._client.get_expired_expiries(underlying_key)
            return sorted(raw_dates)
        except TokenExpiredError as e:
            raise BrokerError(f"Upstox token expired: {e}") from e
        except UpstoxError as e:
            raise BrokerError(f"Failed to get expiries from Upstox: {e}") from e

    def get_option_chain(
        self,
        underlying_key: str,
        expiry: date,
    ) -> list[OptionContract]:
        """Fetch option chain for one expiry from Upstox."""
        try:
            raw_contracts = self._client.get_expired_contracts(underlying_key, expiry)
            return raw_contracts
        except TokenExpiredError as e:
            raise BrokerError(f"Upstox token expired: {e}") from e
        except UpstoxError as e:
            raise BrokerError(f"Failed to get option chain from Upstox: {e}") from e

    def close(self) -> None:
        """Close the Upstox HTTP client."""
        try:
            self._client.close()
        except Exception:
            pass
