"""Upstox API provider (backward compatibility wrapper).

Wraps the existing UpstoxClient to implement BrokerDataProvider interface.
Allows gradual migration from Upstox to other brokers.
"""
from __future__ import annotations

from datetime import date

from bhav.data.provider import BrokerDataProvider, BrokerError, OptionContract


# The concrete Upstox client (bhav.data.upstox_client) is intentionally NOT
# bundled — this project is migrating away from Upstox. Importing it lazily
# keeps this module importable (so the provider factory and test suite don't
# crash) while any real use surfaces a clean BrokerError explaining the gap.
class UpstoxError(BrokerError):
    """Placeholder so callers can `except UpstoxError` even when the real
    Upstox client isn't installed."""


class TokenExpiredError(UpstoxError):
    """Placeholder mirroring the real client's token-expiry error."""


def _load_upstox_client():
    """Import the real UpstoxClient on demand; raise BrokerError if absent."""
    try:
        from bhav.data.upstox_client import UpstoxClient  # type: ignore
        return UpstoxClient
    except ImportError as e:
        raise BrokerError(
            "Upstox support is not bundled in this build (bhav.data.upstox_client "
            "is missing). Use --broker groww or --broker csv instead."
        ) from e


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
        if not token:
            raise BrokerError("Upstox provider requires a non-empty access token")
        UpstoxClient = _load_upstox_client()  # raises BrokerError if not bundled
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
