"""Tests for BrokerDataProvider interface contract."""
import pytest
from datetime import date
from bhav.data.provider import BrokerDataProvider, BrokerError, OptionContract


class DummyProvider(BrokerDataProvider):
    """Minimal concrete implementation for testing interface."""

    def get_spot_candles(self, instrument_key: str, d: date, interval: str = "1minute") -> list[list]:
        return []

    def get_option_candles(self, option_key: str, d: date, interval: str = "1minute") -> list[list]:
        return []

    def get_expiries(self, underlying_key: str) -> list[date]:
        return []

    def get_option_chain(self, underlying_key: str, expiry: date) -> list[OptionContract]:
        return []


def test_provider_interface_exists():
    """Verify BrokerDataProvider is abstract."""
    # Should not be instantiable directly
    with pytest.raises(TypeError):
        BrokerDataProvider()


def test_provider_concrete_implementation():
    """Verify concrete implementations can be created."""
    provider = DummyProvider()
    assert provider is not None


def test_provider_context_manager():
    """Verify provider supports context manager protocol."""
    with DummyProvider() as provider:
        assert provider is not None


def test_provider_close_idempotent():
    """Verify close() can be called multiple times."""
    provider = DummyProvider()
    provider.close()
    provider.close()  # Should not raise


def test_option_contract_immutable():
    """Verify OptionContract is frozen (immutable)."""
    contract = OptionContract(
        instrument_key="NSE_FO|Nifty50",
        strike=24000,
        option_type="CE",
        expiry=date(2025, 1, 16),
    )

    # Should not be able to modify
    with pytest.raises(AttributeError):
        contract.strike = 25000


def test_option_contract_equality():
    """Verify OptionContract equality."""
    c1 = OptionContract("NSE_FO|Nifty50", 24000, "CE", date(2025, 1, 16))
    c2 = OptionContract("NSE_FO|Nifty50", 24000, "CE", date(2025, 1, 16))
    assert c1 == c2


def test_broker_error_exception():
    """Verify BrokerError is exception type."""
    assert issubclass(BrokerError, Exception)

    err = BrokerError("Test error")
    assert str(err) == "Test error"
