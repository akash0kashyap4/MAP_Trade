"""
Runtime configuration for the provider-abstracted AI brain.

Central place for provider selection, timeouts, retries, and logging — all
env-overridable so no code change is needed to switch runtimes. The core RAG /
trading logic never reads provider details directly; it goes through the
provider registry, which reads its settings from here.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LOG_DIR = Path(os.getenv("LOG_DIR", str(_REPO_ROOT / "logs")))


@dataclass(frozen=True)
class RuntimeConfig:
    # Which provider adapter powers the AI brain by default.
    #   claude / anthropic  -> Anthropic API (paid)
    #   claude_code         -> Claude Code CLI (`claude -p`)
    #   copilot / copilot_cli -> GitHub Copilot CLI
    #   ollama              -> local Ollama server
    default_provider: str
    request_timeout_s: int
    max_retries: int
    retry_backoff_s: float
    max_tokens: int
    # provider-specific runtime settings
    claude_cli_bin: str
    copilot_cli_bin: str
    ollama_url: str
    ollama_model: str
    log_level: str


def _load() -> RuntimeConfig:
    # Import the app config package for the .env-derived AI_PROVIDER default.
    import config as appcfg
    return RuntimeConfig(
        default_provider=os.getenv("AI_PROVIDER", getattr(appcfg, "AI_PROVIDER", "claude")).strip().lower(),
        request_timeout_s=int(os.getenv("LLM_TIMEOUT_S", "45")),
        max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),
        retry_backoff_s=float(os.getenv("LLM_RETRY_BACKOFF_S", "2")),
        max_tokens=int(os.getenv("CLAUDE_MAX_TOKENS", "4096")),
        claude_cli_bin=os.getenv("CLAUDE_CLI_BIN", "claude"),
        copilot_cli_bin=os.getenv("COPILOT_CLI_BIN", "copilot"),
        ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/"),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.1"),
        log_level=os.getenv("RUNTIME_LOG_LEVEL", "INFO").upper(),
    )


RUNTIME = _load()

_logger: logging.Logger | None = None


def get_logger() -> logging.Logger:
    """Runtime logger — writes to logs/runtime.log (rotating) and the console."""
    global _logger
    if _logger is not None:
        return _logger
    log = logging.getLogger("map_trade.runtime")
    log.setLevel(getattr(logging, RUNTIME.log_level, logging.INFO))
    log.propagate = False
    if not log.handlers:
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] runtime: %(message)s",
                                datefmt="%Y-%m-%d %H:%M:%S")
        try:
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(_LOG_DIR / "runtime.log", maxBytes=2_000_000, backupCount=3)
            fh.setFormatter(fmt)
            log.addHandler(fh)
        except Exception:
            pass  # file logging is best-effort; never block on it
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        log.addHandler(sh)
    _logger = log
    return log
