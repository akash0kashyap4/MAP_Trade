"""
Provider registry — the single point the core logic uses to reach an LLM.

The trading/RAG code calls `get_active_provider().ask(...)`; it never imports a
concrete adapter. Provider selection is configuration-driven (config.runtime →
AI_PROVIDER). New runtimes are added by writing an adapter and registering it
here — no change to business logic.
"""
from __future__ import annotations

from config.runtime import RUNTIME
from ai.providers.base import BaseProvider, ProviderError

# name (and aliases) -> adapter class
_CLASSES: dict[str, type[BaseProvider]] = {}
# name -> cached instance (providers are reused across calls / runtime reuse)
_INSTANCES: dict[str, BaseProvider] = {}


def _register_builtins() -> None:
    if _CLASSES:
        return
    from ai.providers.anthropic_api import AnthropicAPIProvider
    from ai.providers.gemini import GeminiProvider
    from ai.providers.claude_code import ClaudeCodeCLIProvider
    from ai.providers.copilot_cli import CopilotCLIProvider
    from ai.providers.ollama import OllamaProvider

    _CLASSES.update({
        # Anthropic API (paid). "claude" is the historical alias kept for .env compat.
        "claude": AnthropicAPIProvider,
        "anthropic": AnthropicAPIProvider,
        "anthropic_api": AnthropicAPIProvider,
        # Google Gemini (free tier)
        "gemini": GeminiProvider,
        # Claude Code CLI (local `claude -p`)
        "claude_code": ClaudeCodeCLIProvider,
        "claude-code": ClaudeCodeCLIProvider,
        "cli": ClaudeCodeCLIProvider,
        # GitHub Copilot CLI
        "copilot": CopilotCLIProvider,
        "copilot_cli": CopilotCLIProvider,
        # Local Ollama
        "ollama": OllamaProvider,
    })


def register(name: str, cls: type[BaseProvider]) -> None:
    """Register (or override) a provider adapter under `name`."""
    _register_builtins()
    _CLASSES[name.strip().lower()] = cls


def available_providers() -> list[str]:
    _register_builtins()
    return sorted(set(_CLASSES))


def get_provider(name: str | None = None) -> BaseProvider:
    """Return a cached provider instance by name (defaults to the active one).

    `name` may be a single provider ("claude_code") or a comma-separated
    fallback chain ("claude_code,copilot,claude") — the chain is tried in
    order and the first provider to succeed serves the response.
    """
    _register_builtins()
    key = (name or RUNTIME.default_provider or "claude").strip().lower()

    if "," in key:
        if key not in _INSTANCES:
            from ai.providers.fallback import FallbackChainProvider
            links = [get_provider(part.strip()) for part in key.split(",") if part.strip()]
            _INSTANCES[key] = FallbackChainProvider(RUNTIME, links)
        return _INSTANCES[key]

    cls = _CLASSES.get(key)
    if cls is None:
        raise ProviderError("registry",
                            f"unknown provider '{key}'. Available: {available_providers()}")
    if key not in _INSTANCES:
        _INSTANCES[key] = cls(RUNTIME)
    return _INSTANCES[key]


def get_active_provider() -> BaseProvider:
    """The provider selected by config.runtime.RUNTIME.default_provider (AI_PROVIDER)."""
    return get_provider(RUNTIME.default_provider)


def reset_instances() -> None:
    """Drop cached instances (used by tests and after a runtime change)."""
    _INSTANCES.clear()
