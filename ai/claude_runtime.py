"""
Claude Code CLI runtime facade.

Thin convenience layer over the provider registry for the primary/default
Claude Code CLI runtime. Exposes the same normalized interface as any provider
(ask / stream / health_check / restart / shutdown) so callers that specifically
want the Claude Code runtime can reach it without touching the adapter directly.
"""
from __future__ import annotations

from ai.provider_registry import get_provider
from ai.providers.base import LLMResponse


def get_claude_runtime():
    """Return the Claude Code CLI provider instance."""
    return get_provider("claude_code")


def ask(system: str, user: str, max_tokens: int | None = None) -> LLMResponse:
    return get_claude_runtime().ask(system, user, max_tokens)


def health_check() -> bool:
    return get_claude_runtime().health_check()


def shutdown() -> None:
    get_claude_runtime().shutdown()
