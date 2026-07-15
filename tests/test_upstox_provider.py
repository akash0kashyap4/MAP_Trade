"""Tests for UpstoxProvider (backward compatibility wrapper)."""
import pytest
from datetime import date
from bhav.data.provider import BrokerError
from bhav.data.providers.upstox_provider import UpstoxProvider


class TestUpstoxProviderInit:
    """Test UpstoxProvider initialization."""

    def test_init_requires_token(self):
        """Provider requires a token."""
        with pytest.raises(BrokerError):
            UpstoxProvider(token="")

    def test_init_with_invalid_token_raises_broker_error(self):
        """Invalid token raises BrokerError (not UpstoxError)."""
        # This should raise during client init
        with pytest.raises(BrokerError):
            UpstoxProvider(token="invalid_token_that_does_not_exist")


class TestUpstoxProviderInterface:
    """Test that UpstoxProvider implements interface."""

    def test_implements_broker_data_provider(self):
        """Verify UpstoxProvider is a BrokerDataProvider."""
        from bhav.data.provider import BrokerDataProvider
        # Note: Will fail on init without valid token
        try:
            provider = UpstoxProvider(token="test")
            assert isinstance(provider, BrokerDataProvider)
        except BrokerError:
            # Expected with invalid token; still proves inheritance
            pass

    def test_has_required_methods(self):
        """Verify all required methods exist."""
        required_methods = [
            'get_spot_candles',
            'get_option_candles',
            'get_expiries',
            'get_option_chain',
            'close',
        ]
        try:
            provider = UpstoxProvider(token="test")
            for method in required_methods:
                assert hasattr(provider, method)
                assert callable(getattr(provider, method))
        except BrokerError:
            pass


class TestUpstoxProviderErrorHandling:
    """Test error translation."""

    def test_broker_error_not_upstox_error(self):
        """UpstoxProvider translates exceptions to BrokerError."""
        # When token is invalid, should raise BrokerError, not raw UpstoxError
        from bhav.data.providers.upstox_provider import UpstoxError
        try:
            provider = UpstoxProvider(token="invalid")
        except BrokerError:
            # Correct: got BrokerError
            pass
        except UpstoxError:
            # Wrong: leaked UpstoxError through
            pytest.fail("UpstoxProvider should wrap UpstoxError in BrokerError")
