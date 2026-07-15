"""Tests for LocalCsvProvider."""
import pytest
from datetime import date
from pathlib import Path
from bhav.data.providers.local_csv_provider import LocalCsvProvider
from bhav.data.provider import BrokerError


class TestLocalCsvProviderInit:
    """Test LocalCsvProvider initialization."""

    def test_init_creates_directories(self, tmp_path):
        """Provider creates missing directories."""
        data_dir = tmp_path / "data"
        provider = LocalCsvProvider(data_dir)

        # Should create directories
        assert (data_dir / "spot").exists()
        assert (data_dir / "options").exists()

    def test_init_with_existing_directories(self, tmp_path):
        """Provider works with existing directories."""
        data_dir = tmp_path / "data"
        (data_dir / "spot").mkdir(parents=True)
        (data_dir / "options").mkdir(parents=True)

        provider = LocalCsvProvider(data_dir)
        assert (data_dir / "spot").exists()
        assert (data_dir / "options").exists()


class TestLocalCsvProviderInterface:
    """Test LocalCsvProvider implements interface."""

    def test_implements_broker_data_provider(self, tmp_path):
        """Verify it's a BrokerDataProvider."""
        from bhav.data.provider import BrokerDataProvider
        provider = LocalCsvProvider(tmp_path)
        assert isinstance(provider, BrokerDataProvider)

    def test_has_required_methods(self, tmp_path):
        """Verify all required methods exist."""
        required_methods = [
            'get_spot_candles',
            'get_option_candles',
            'get_expiries',
            'get_option_chain',
            'close',
        ]
        provider = LocalCsvProvider(tmp_path)
        for method in required_methods:
            assert hasattr(provider, method)
            assert callable(getattr(provider, method))


class TestLocalCsvProviderReturnTypes:
    """Test return types for missing files."""

    def test_missing_spot_file_returns_empty(self, tmp_path):
        """Missing file returns empty list."""
        provider = LocalCsvProvider(tmp_path)
        result = provider.get_spot_candles("NSE_INDEX_Nifty50", date(2025, 1, 16))
        assert isinstance(result, list)
        assert len(result) == 0

    def test_missing_option_file_returns_empty(self, tmp_path):
        """Missing file returns empty list."""
        provider = LocalCsvProvider(tmp_path)
        result = provider.get_option_candles("NSE_INDEX_Nifty50_2025-01-16_24000_CE", date(2025, 1, 16))
        assert isinstance(result, list)
        assert len(result) == 0

    def test_expiries_returns_empty_list(self, tmp_path):
        """Expiries returns list (empty if no files)."""
        provider = LocalCsvProvider(tmp_path)
        result = provider.get_expiries("NSE_INDEX_Nifty50")
        assert isinstance(result, list)

    def test_option_chain_returns_empty_list(self, tmp_path):
        """Option chain returns empty list."""
        provider = LocalCsvProvider(tmp_path)
        result = provider.get_option_chain("NSE_INDEX_Nifty50", date(2025, 1, 16))
        assert isinstance(result, list)
        assert len(result) == 0


class TestLocalCsvProviderSanitizeFilename:
    """Test filename sanitization."""

    def test_sanitize_removes_pipes(self):
        """Pipes are replaced with underscores."""
        result = LocalCsvProvider._sanitize_filename("NSE_INDEX|Nifty 50")
        assert "|" not in result
        assert "_" in result

    def test_sanitize_removes_spaces(self):
        """Spaces are removed."""
        result = LocalCsvProvider._sanitize_filename("NSE_INDEX|Nifty 50")
        assert " " not in result

    def test_sanitize_handles_dashes(self):
        """Dashes are replaced with underscores."""
        result = LocalCsvProvider._sanitize_filename("Nifty-50-01Jan2025")
        assert "-" not in result


class TestLocalCsvProviderContextManager:
    """Test context manager support."""

    def test_context_manager(self, tmp_path):
        """Provider can be used with 'with' statement."""
        with LocalCsvProvider(tmp_path) as provider:
            assert provider is not None

    def test_close_is_idempotent(self, tmp_path):
        """close() can be called multiple times."""
        provider = LocalCsvProvider(tmp_path)
        provider.close()
        provider.close()  # Should not raise
