"""Pytest configuration — add repo root to sys.path for all tests."""
import sys
import os
from unittest.mock import MagicMock

# Ensure repo root is on sys.path so tests can import project modules directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub optional heavy dependencies so tests can import project modules without
# installing the full production dependency set.
for _mod in ("yfinance", "growwapi", "curl_cffi", "curl_cffi.requests",
             "aiosqlite", "asyncpg", "colorama",
             "colorama.Fore", "colorama.Style"):
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
