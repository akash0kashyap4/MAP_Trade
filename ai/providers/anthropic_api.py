"""Anthropic API adapter (paid). The most consistent runtime for live trading."""
from __future__ import annotations

import os

from ai.providers.base import BaseProvider, ProviderError

_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")


class AnthropicAPIProvider(BaseProvider):
    name = "anthropic"

    def _generate(self, system: str, user: str, max_tokens: int | None) -> str:
        import config
        if not config.ANTHROPIC_API_KEY:
            raise ProviderError(self.name, "ANTHROPIC_API_KEY not set in .env")
        try:
            from anthropic import Anthropic
        except Exception as e:  # pragma: no cover
            raise ProviderError(self.name, f"anthropic SDK not installed: {e}", cause=e)

        client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=os.getenv("CLAUDE_MODEL", _MODEL),
            max_tokens=max_tokens or self.settings.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        if getattr(resp, "stop_reason", None) == "max_tokens":
            from config.runtime import get_logger
            get_logger().warning("provider=%s hit max_tokens — output may be truncated", self.name)
        return resp.content[0].text

    def health_check(self) -> bool:
        import config
        return bool(config.ANTHROPIC_API_KEY)
