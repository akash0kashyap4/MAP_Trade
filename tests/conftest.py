"""Pytest configuration — add repo root to sys.path for all tests."""
import sys
import os
from unittest.mock import MagicMock

# Ensure repo root is on sys.path so tests can import project modules directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub optional heavy dependencies so tests can import project modules without
# installing the full production dependency set.
for _mod in (
    # Trading / data feed deps not available in CI
    "yfinance", "growwapi", "curl_cffi", "curl_cffi.requests",
    "smartapi", "smartapi.smartConnect",
    # Async DB drivers
    "aiosqlite", "asyncpg",
    # HTTP / networking
    "aiohttp", "aiohttp.web", "websockets",
    "requests",  # pulled in by groww/oauth.py at module level
    # Telegram
    "telegram", "telegram.ext", "python_telegram_bot",
    # AI / LLM
    "anthropic",
    # Web framework stubs (real fastapi/pydantic are installed — only stub sub-paths missing locally)
    "uvicorn", "fastapi",
    "fastapi.responses", "fastapi.staticfiles",
    # Colorama
    "colorama", "colorama.Fore", "colorama.Style",
    # Scheduler
    "apscheduler",
    "apscheduler.schedulers", "apscheduler.schedulers.asyncio",
    "apscheduler.triggers", "apscheduler.triggers.cron",
):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

# colorama needs real string attributes for string formatting
import colorama as _ca  # noqa: E402  (after mock registration)
_ca.Fore = MagicMock()
_ca.Style = MagicMock()
_ca.Fore.CYAN = ""
_ca.Fore.YELLOW = ""
_ca.Fore.GREEN = ""
_ca.Fore.RED = ""
_ca.Fore.WHITE = ""
_ca.Style.RESET_ALL = ""


# ── Test Fixtures ────────────────────────────────────────────────────────

import pytest
from datetime import date


@pytest.fixture
def sample_date():
    """Sample date for testing."""
    return date(2025, 1, 16)


@pytest.fixture
def nifty_instrument_key():
    """Standard NIFTY 50 instrument key."""
    return "NSE_INDEX|Nifty 50"


@pytest.fixture
def option_key():
    """Sample option key in normalized format."""
    return "NSE_INDEX|Nifty 50|2025-01-16|24000|CE"


@pytest.fixture
def sample_spot_candle():
    """Sample spot candle data."""
    return [
        "2025-01-16T09:15:00+05:30",  # timestamp
        23900.0,                       # open
        24000.0,                       # high
        23850.0,                       # low
        23950.0,                       # close
        10000,                         # volume
        0,                             # oi
    ]


@pytest.fixture
def sample_spot_candles(sample_spot_candle):
    """Multiple spot candles for a day."""
    return [
        sample_spot_candle,
        ["2025-01-16T09:16:00+05:30", 23950, 24010, 23930, 23980, 8500, 0],
        ["2025-01-16T09:17:00+05:30", 23980, 24050, 23970, 24020, 9200, 0],
    ]
