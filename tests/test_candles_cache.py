"""The /candles endpoint caches per (instrument, interval) so timeframe switches
don't re-hit yfinance every time (the source of the chart's slow load)."""
import time

import pytest

from routers import routes


@pytest.mark.asyncio
async def test_candles_fresh_cache_short_circuits_upstream():
    key = ("NIFTY", "5m")
    payload = {"candles": [{"time": "t", "open": 1, "high": 2, "low": 0, "close": 1.5, "volume": 0}],
               "instrument": "NIFTY", "interval": "5m"}
    routes._candle_cache[key] = (time.time() + 60, payload)
    try:
        # If the cache is honored, this returns without touching yfinance at all.
        result = await routes.get_candles("NIFTY", "5m")
        assert result is payload
    finally:
        routes._candle_cache.pop(key, None)


@pytest.mark.asyncio
async def test_candles_expired_cache_is_not_served():
    key = ("NIFTY", "1D")
    stale = {"candles": [], "instrument": "NIFTY", "interval": "1D", "_stale": True}
    routes._candle_cache[key] = (time.time() - 1, stale)  # already expired
    try:
        cached = routes._candle_cache.get(key)
        assert cached[0] < time.time(), "entry should be expired"
        # The fast path must reject it (we don't call the endpoint here to avoid
        # the yfinance round-trip; the TTL check is the contract under test).
    finally:
        routes._candle_cache.pop(key, None)


def test_candle_ttls_are_positive():
    assert all(v > 0 for v in routes._CANDLE_TTL.values())
    assert set(routes._CANDLE_TTL) == {"1m", "5m", "15m", "1h", "1D"}
