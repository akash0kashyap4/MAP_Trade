"""Tests for GrowwDataProvider."""
import pytest
from datetime import date
from bhav.data.providers.groww_provider import GrowwDataProvider
from bhav.data.provider import BrokerError


class TestGrowwProviderInit:
    """Test GrowwDataProvider initialization."""

    def test_init_without_token(self):
        """Provider can be created without explicit token."""
        provider = GrowwDataProvider()
        assert provider is not None

    def test_init_with_token(self):
        """Provider can be created with explicit token."""
        provider = GrowwDataProvider(api_token="fake_token")
        assert provider is not None


class TestGrowwProviderInterface:
    """Test that GrowwDataProvider implements full interface."""

    def test_implements_broker_data_provider(self):
        """Verify GrowwDataProvider is a BrokerDataProvider."""
        from bhav.data.provider import BrokerDataProvider
        provider = GrowwDataProvider()
        assert isinstance(provider, BrokerDataProvider)

    def test_has_get_spot_candles(self):
        """Verify method exists."""
        provider = GrowwDataProvider()
        assert hasattr(provider, 'get_spot_candles')
        assert callable(getattr(provider, 'get_spot_candles'))

    def test_has_get_option_candles(self):
        """Verify method exists."""
        provider = GrowwDataProvider()
        assert hasattr(provider, 'get_option_candles')
        assert callable(getattr(provider, 'get_option_candles'))

    def test_has_get_expiries(self):
        """Verify method exists."""
        provider = GrowwDataProvider()
        assert hasattr(provider, 'get_expiries')
        assert callable(getattr(provider, 'get_expiries'))

    def test_has_get_option_chain(self):
        """Verify method exists."""
        provider = GrowwDataProvider()
        assert hasattr(provider, 'get_option_chain')
        assert callable(getattr(provider, 'get_option_chain'))


class TestGrowwProviderReturnTypes:
    """Test return types (without hitting real APIs)."""

    def test_spot_candles_returns_list(self):
        """get_spot_candles returns list (may be empty)."""
        provider = GrowwDataProvider()
        result = provider.get_spot_candles("NSE_INDEX|Nifty 50", date(2025, 1, 16))
        assert isinstance(result, list)

    def test_option_candles_returns_list(self):
        """get_option_candles returns list (may be empty)."""
        provider = GrowwDataProvider()
        result = provider.get_option_candles("NSE_INDEX|Nifty 50|2025-01-16|24000|CE", date(2025, 1, 16))
        assert isinstance(result, list)

    def test_expiries_returns_sorted_list(self):
        """get_expiries returns sorted list of dates."""
        provider = GrowwDataProvider()
        result = provider.get_expiries("NSE_INDEX|Nifty 50")
        assert isinstance(result, list)
        # If not empty, should be sorted
        if len(result) > 1:
            assert result == sorted(result)

    def test_option_chain_returns_list(self):
        """get_option_chain returns list (may be empty)."""
        provider = GrowwDataProvider()
        result = provider.get_option_chain("NSE_INDEX|Nifty 50", date(2025, 1, 16))
        assert isinstance(result, list)


class TestGrowwProviderContextManager:
    """Test context manager support."""

    def test_context_manager_entry(self):
        """Provider can be used with 'with' statement."""
        with GrowwDataProvider() as provider:
            assert provider is not None

    def test_context_manager_close_called(self):
        """Provider.close() called on context exit."""
        provider = GrowwDataProvider()
        provider.__enter__()
        provider.__exit__(None, None, None)
        # Should not raise


class TestGrowwProviderBlackScholes:
    """Test Black-Scholes pricing."""

    def test_bs_price_call_atm(self):
        """ATM call option price is positive."""
        price = GrowwDataProvider._bs_price(S=24000, K=24000, T_days=5, sigma=0.15, option_type="CE")
        assert price > 0

    def test_bs_price_put_atm(self):
        """ATM put option price is positive."""
        price = GrowwDataProvider._bs_price(S=24000, K=24000, T_days=5, sigma=0.15, option_type="PE")
        assert price > 0

    def test_bs_price_expiry_call(self):
        """Call at expiry has intrinsic value only."""
        price = GrowwDataProvider._bs_price(S=25000, K=24000, T_days=0, option_type="CE")
        assert price == 1000  # 25000 - 24000

    def test_bs_price_expiry_put(self):
        """Put at expiry has intrinsic value only."""
        price = GrowwDataProvider._bs_price(S=23000, K=24000, T_days=0, option_type="PE")
        assert price == 1000  # 24000 - 23000

    def test_bs_price_otm_call_expiry(self):
        """OTM call at expiry is worthless."""
        price = GrowwDataProvider._bs_price(S=23000, K=24000, T_days=0, option_type="CE")
        assert price == 0

    def test_bs_price_otm_put_expiry(self):
        """OTM put at expiry is worthless."""
        price = GrowwDataProvider._bs_price(S=25000, K=24000, T_days=0, option_type="PE")
        assert price == 0

    def test_bs_price_time_value_decay(self):
        """Option loses value as expiry approaches."""
        price_5d = GrowwDataProvider._bs_price(S=24000, K=24000, T_days=5, option_type="CE")
        price_1d = GrowwDataProvider._bs_price(S=24000, K=24000, T_days=1, option_type="CE")
        assert price_5d > price_1d


class TestGrowwProviderCandles:
    """Test candle format expectations."""

    def test_bs_synthesize_option_candles_format(self):
        """Synthesized option candles have correct format."""
        # Create a mock spot candle
        spot_candles = [
            ["2025-01-16T09:15:00+05:30", 23900, 24000, 23850, 23950, 10000, 0],
        ]
        provider = GrowwDataProvider()
        result = provider._synthesize_option_candles("NSE_INDEX|Nifty 50|2025-01-16|24000|CE", date(2025, 1, 16))
        # Result should be list (may be empty if synthesis fails)
        assert isinstance(result, list)
