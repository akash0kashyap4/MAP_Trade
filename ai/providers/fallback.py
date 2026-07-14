"""
Fallback-chain provider — tries an ordered list of adapters, returns the first
success. Lets AI_PROVIDER name multiple runtimes (e.g. "claude_code,copilot,claude")
so a CLI outage doesn't take the trading bot's AI brain down with it.
"""
from __future__ import annotations

from typing import Iterator

from ai.providers.base import BaseProvider, LLMResponse


class FallbackChainProvider(BaseProvider):
    name = "fallback_chain"

    def __init__(self, settings, providers: list[BaseProvider]):
        super().__init__(settings)
        self._providers = providers

    def _generate(self, system: str, user: str, max_tokens: int | None) -> str:
        raise NotImplementedError  # ask() is overridden directly; each link retries on its own

    def ask(self, system: str, user: str, max_tokens: int | None = None) -> LLMResponse:
        from config.runtime import get_logger
        log = get_logger()
        last: LLMResponse | None = None
        for i, p in enumerate(self._providers):
            resp = p.ask(system, user, max_tokens)
            if resp.success:
                if i > 0:
                    log.warning("fallback_chain: primary(s) failed, served by %s", p.name)
                return resp
            last = resp
        log.error("fallback_chain: all providers failed [%s]",
                  ",".join(p.name for p in self._providers))
        return last if last is not None else LLMResponse(False, "", "", 0, self.name)

    def health_check(self) -> bool:
        return any(p.health_check() for p in self._providers)

    def stream(self, system: str, user: str, max_tokens: int | None = None) -> Iterator[str]:
        resp = self.ask(system, user, max_tokens)
        if resp.success:
            yield resp.text
