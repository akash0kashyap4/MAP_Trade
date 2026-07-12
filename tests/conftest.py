"""Pytest configuration — add repo root to sys.path for all tests."""
import sys
import os
from unittest.mock import MagicMock

# Ensure repo root is on sys.path so tests can import project modules directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub optional heavy dependencies so tests can import project modules without
# installing the full production dependency set.
import importlib.util as _ilu


def _stub(mod: str) -> None:
    """Register a MagicMock for `mod` only if it isn't genuinely importable.

    fastapi/uvicorn/httpx are real dependencies of the app and are installed in
    CI; the HTTP-level security suite (tests/test_security.py) needs the real
    FastAPI + TestClient, so we must never shadow them with a mock. Anything not
    installed still gets stubbed so the pure-unit tests keep importing.
    """
    if mod in sys.modules:
        return
    try:
        if _ilu.find_spec(mod) is not None:
            return  # real module available — use it
    except (ImportError, ModuleNotFoundError, ValueError):
        pass
    sys.modules[mod] = MagicMock()


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
    # Web framework: stubbed only if truly missing (see _stub docstring)
    "uvicorn", "fastapi",
    "fastapi.responses", "fastapi.staticfiles",
    # Colorama
    "colorama", "colorama.Fore", "colorama.Style",
    # Scheduler
    "apscheduler",
    "apscheduler.schedulers", "apscheduler.schedulers.asyncio",
    "apscheduler.triggers", "apscheduler.triggers.cron",
):
    _stub(_mod)

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
