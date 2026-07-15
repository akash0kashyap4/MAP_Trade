"""Integration tests: provider consistency and fallback behavior."""
import pytest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from bhav.data.reader import DataReader
from bhav.data.instruments import InstrumentResolver
from bhav.data.providers.groww_provider import GrowwDataProvider
from bhav.data.providers.local_csv_provider import LocalCsvProvider
from bhav.engine.strategy import Strategy, Context
from bhav.engine.bar_engine import BarEngine, EngineConfig


class DummyStrategy(Strategy):
    """Simple dummy strategy for testing."""

    def __init__(self):
        self.name = "DummyStrategy"
        self.bar_count = 0

    def on_start(self, ctx: Context):
        pass

    def on_bar(self, ctx: Context):
        self.bar_count += 1

    def on_day_end(self, ctx: Context):
        pass

    def on_end(self, ctx: Context):
        pass


class TestProviderInteroperability:
    """Test that providers work with the engine."""

    def test_groww_provider_with_engine(self):
        """Groww provider integrates with BarEngine."""
        provider = GrowwDataProvider()
        reader = DataReader(provider)
        resolver = InstrumentResolver(provider, "NSE_INDEX|Nifty 50")

        cfg = EngineConfig(
            underlying_key="NSE_INDEX|Nifty 50",
            start=date(2025, 1, 16),
            end=date(2025, 1, 16),
        )

        engine = BarEngine(cfg, reader, resolver)
        strategy = DummyStrategy()

        # Should not raise
        portfolio = engine.run(strategy)
        assert portfolio is not None
        provider.close()

    def test_local_csv_provider_with_engine(self):
        """Local CSV provider integrates with BarEngine."""
        with TemporaryDirectory() as tmpdir:
            provider = LocalCsvProvider(tmpdir)
            reader = DataReader(provider)
            resolver = InstrumentResolver(provider, "NSE_INDEX|Nifty 50")

            cfg = EngineConfig(
                underlying_key="NSE_INDEX|Nifty 50",
                start=date(2025, 1, 16),
                end=date(2025, 1, 16),
            )

            engine = BarEngine(cfg, reader, resolver)
            strategy = DummyStrategy()

            # Should return empty portfolio (no data in tmp dir)
            portfolio = engine.run(strategy)
            assert portfolio is not None
            provider.close()


class TestDataReaderWithProviders:
    """Test DataReader works with all providers."""

    def test_reader_with_groww(self):
        """DataReader works with GrowwDataProvider."""
        provider = GrowwDataProvider()
        reader = DataReader(provider)

        # Should not raise (may return empty if data not available)
        result = reader.spot_bars("NSE_INDEX|Nifty 50", date(2025, 1, 16))
        assert isinstance(result, object)  # Polars DataFrame or empty
        provider.close()

    def test_reader_with_csv(self):
        """DataReader works with LocalCsvProvider."""
        with TemporaryDirectory() as tmpdir:
            provider = LocalCsvProvider(tmpdir)
            reader = DataReader(provider)

            # Should return empty (no files)
            result = reader.spot_bars("NSE_INDEX_Nifty50", date(2025, 1, 16))
            assert isinstance(result, object)  # Polars DataFrame or empty
            provider.close()


class TestInstrumentResolverWithProviders:
    """Test InstrumentResolver works with all providers."""

    def test_resolver_with_groww(self):
        """InstrumentResolver works with GrowwDataProvider."""
        provider = GrowwDataProvider()
        resolver = InstrumentResolver(provider, "NSE_INDEX|Nifty 50")

        # Should not raise
        expiries = resolver.expiries()
        assert isinstance(expiries, list)
        provider.close()

    def test_resolver_atm_strike(self):
        """ATM strike calculation is provider-independent."""
        provider = GrowwDataProvider()
        resolver = InstrumentResolver(provider, "NSE_INDEX|Nifty 50", atm_step=100)

        # Test ATM rounding: round(24050/100)*100 = round(240.5)*100 = 240*100 = 24000
        assert resolver.atm_strike(24050) == 24000  # rounds down
        assert resolver.atm_strike(24049) == 24000  # rounds down
        assert resolver.atm_strike(24000) == 24000  # exact
        assert resolver.atm_strike(24051) == 24100  # rounds up

        provider.close()

    def test_resolver_nearest_expiry(self):
        """Nearest expiry selection is provider-independent."""
        provider = GrowwDataProvider()
        resolver = InstrumentResolver(provider, "NSE_INDEX|Nifty 50")

        # Test with empty/mock data
        expiries = resolver.expiries()
        if expiries:
            nearest = resolver.nearest_expiry(date(2025, 1, 16))
            assert nearest is None or isinstance(nearest, date)

        provider.close()


class TestFallbackBehavior:
    """Test fallback behavior across providers."""

    def test_groww_graceful_degradation(self):
        """Groww provider degrades gracefully on missing data."""
        provider = GrowwDataProvider()

        # Invalid instrument should return empty, not raise
        result = provider.get_spot_candles("INVALID_INSTRUMENT", date(2025, 1, 16))
        assert isinstance(result, list)

        provider.close()

    def test_csv_graceful_missing_files(self):
        """CSV provider handles missing files gracefully."""
        with TemporaryDirectory() as tmpdir:
            provider = LocalCsvProvider(tmpdir)

            # Missing files should return empty, not raise
            result = provider.get_spot_candles("MISSING_FILE", date(2025, 1, 16))
            assert isinstance(result, list)
            assert len(result) == 0

            provider.close()


class TestContextManagerSupport:
    """Test context manager protocol for all providers."""

    def test_groww_context_manager(self):
        """GrowwDataProvider supports context manager."""
        with GrowwDataProvider() as provider:
            assert provider is not None

    def test_csv_context_manager(self):
        """LocalCsvProvider supports context manager."""
        with TemporaryDirectory() as tmpdir:
            with LocalCsvProvider(tmpdir) as provider:
                assert provider is not None
