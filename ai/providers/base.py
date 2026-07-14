"""
Base provider contract for the AI brain.

Every runtime (Anthropic API, Claude Code CLI, Copilot CLI, Ollama)
implements the same interface and normalizes its output into `LLMResponse`. The
core trading/RAG logic depends only on this contract — never on a concrete
provider. Shared retry, timing, and logging live in `BaseProvider.ask`; adapters
implement only `_generate` (and optionally `health_check` / lifecycle hooks).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterator


class ProviderError(Exception):
    """Structured provider failure — carries the provider name and the cause."""

    def __init__(self, provider: str, message: str, *, cause: Exception | None = None):
        self.provider = provider
        self.cause = cause
        super().__init__(f"[{provider}] {message}")


@dataclass
class LLMResponse:
    """Normalized response returned by every provider."""
    success: bool
    text: str
    raw: str
    execution_ms: int
    provider: str


class BaseProvider:
    """Common wrapper: retries, timing, structured logging, graceful failure."""

    name: str = "base"

    def __init__(self, settings):
        self.settings = settings  # config.runtime.RuntimeConfig

    # ── adapters implement this ──────────────────────────────────────────────
    def _generate(self, system: str, user: str, max_tokens: int | None) -> str:
        raise NotImplementedError

    # ── lifecycle hooks (overridable) ────────────────────────────────────────
    def health_check(self) -> bool:
        return True

    def restart(self) -> None:
        """Reset any long-lived runtime state. Stateless providers: no-op."""

    def shutdown(self) -> None:
        """Release resources / stop child processes. Stateless providers: no-op."""

    # ── shared execution path ────────────────────────────────────────────────
    def ask(self, system: str, user: str, max_tokens: int | None = None) -> LLMResponse:
        from config.runtime import get_logger
        log = get_logger()
        retries = self.settings.max_retries
        overall = time.time()
        last_err: Exception | None = None

        for attempt in range(retries + 1):
            t0 = time.time()
            try:
                text = self._generate(system, user, max_tokens)
                ms = int((time.time() - t0) * 1000)
                if text:
                    log.info("provider=%s ok attempt=%d execution_ms=%d", self.name, attempt + 1, ms)
                    return LLMResponse(True, text, text, ms, self.name)
                last_err = ProviderError(self.name, "empty response")
                log.warning("provider=%s empty attempt=%d execution_ms=%d", self.name, attempt + 1, ms)
            except ProviderError as e:
                last_err = e
                log.warning("provider=%s FAILED attempt=%d: %s", self.name, attempt + 1, e)
            except Exception as e:  # normalize any adapter exception
                last_err = ProviderError(self.name, str(e), cause=e)
                log.warning("provider=%s ERROR attempt=%d [%s]: %s",
                            self.name, attempt + 1, type(e).__name__, e)
            if attempt < retries:
                log.info("provider=%s retry in %.1fs", self.name, self.settings.retry_backoff_s)
                time.sleep(self.settings.retry_backoff_s)

        ms = int((time.time() - overall) * 1000)
        log.error("provider=%s exhausted retries execution_ms=%d last_error=%s",
                  self.name, ms, last_err)
        return LLMResponse(False, "", "", ms, self.name)

    def stream(self, system: str, user: str, max_tokens: int | None = None) -> Iterator[str]:
        """Default streaming = one chunk from ask(). Adapters with native
        streaming override this; callers get a graceful fallback either way."""
        resp = self.ask(system, user, max_tokens)
        if resp.success:
            yield resp.text
