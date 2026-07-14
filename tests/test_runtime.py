"""Tests for the provider-abstraction runtime: registry, contract, adapters."""
from unittest.mock import MagicMock, patch

import pytest

from ai.providers.base import BaseProvider, LLMResponse, ProviderError
from config.runtime import RUNTIME
import ai.provider_registry as registry


# ── a fake adapter to exercise the shared BaseProvider path ───────────────────

class _FlakyProvider(BaseProvider):
    name = "flaky"

    def __init__(self, settings, fail_times=0, text="ok"):
        super().__init__(settings)
        self._fail_times = fail_times
        self._text = text
        self.calls = 0

    def _generate(self, system, user, max_tokens):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise ProviderError(self.name, "boom")
        return self._text


def _settings(**over):
    from dataclasses import replace
    return replace(RUNTIME, **over)


# ── contract / normalized response ────────────────────────────────────────────

def test_response_is_normalized_on_success():
    p = _FlakyProvider(_settings(max_retries=0), fail_times=0, text="hello")
    r = p.ask("sys", "user")
    assert isinstance(r, LLMResponse)
    assert r.success and r.text == "hello" and r.provider == "flaky"
    assert r.execution_ms >= 0


def test_retry_then_succeed():
    p = _FlakyProvider(_settings(max_retries=2, retry_backoff_s=0), fail_times=1, text="ok")
    r = p.ask("s", "u")
    assert r.success and p.calls == 2


def test_exhausted_retries_returns_failure_not_exception():
    p = _FlakyProvider(_settings(max_retries=1, retry_backoff_s=0), fail_times=5)
    r = p.ask("s", "u")
    assert r.success is False and r.text == "" and r.provider == "flaky"


def test_empty_response_is_a_failure():
    p = _FlakyProvider(_settings(max_retries=0), fail_times=0, text="")
    assert p.ask("s", "u").success is False


def test_stream_falls_back_to_single_chunk():
    p = _FlakyProvider(_settings(max_retries=0), text="streamed")
    assert list(p.stream("s", "u")) == ["streamed"]


# ── registry / selection ──────────────────────────────────────────────────────

def test_default_provider_matches_config():
    prov = registry.get_active_provider()
    assert prov.name in {"anthropic", "claude_code", "copilot_cli", "ollama", "fallback_chain"}


def test_unknown_provider_raises_structured():
    with pytest.raises(ProviderError):
        registry.get_provider("does-not-exist")


def test_known_aliases_resolve():
    assert registry.get_provider("claude").name == "anthropic"
    assert registry.get_provider("claude-code").name == "claude_code"
    assert registry.get_provider("ollama").name == "ollama"


def test_instances_are_reused():
    a = registry.get_provider("ollama")
    b = registry.get_provider("ollama")
    assert a is b


# ── fallback chain ─────────────────────────────────────────────────────────────

def test_fallback_chain_uses_first_success():
    prov = registry.get_provider("claude_code,ollama")
    assert prov.name == "fallback_chain"


def test_fallback_chain_falls_through_on_failure():
    from ai.providers.fallback import FallbackChainProvider
    a = _FlakyProvider(_settings(max_retries=0), fail_times=99)
    a.name = "a"
    b = _FlakyProvider(_settings(max_retries=0), fail_times=0, text="from-b")
    b.name = "b"
    chain = FallbackChainProvider(_settings(), [a, b])
    r = chain.ask("s", "u")
    assert r.success and r.text == "from-b" and r.provider == "b"


def test_fallback_chain_fails_when_all_fail():
    from ai.providers.fallback import FallbackChainProvider
    a = _FlakyProvider(_settings(max_retries=0), fail_times=99)
    chain = FallbackChainProvider(_settings(), [a])
    assert chain.ask("s", "u").success is False


# ── adapter behaviour (mocked I/O) ────────────────────────────────────────────

def test_claude_code_health_check_uses_which(monkeypatch):
    prov = registry.get_provider("claude_code")
    with patch("shutil.which", return_value="/usr/bin/claude"):
        assert prov.health_check() is True
    with patch("shutil.which", return_value=None):
        assert prov.health_check() is False


def test_claude_code_missing_binary_is_structured_error():
    prov = registry.get_provider("claude_code")
    with patch("subprocess.run", side_effect=FileNotFoundError("no claude")):
        r = prov.ask("s", "u")           # ask() swallows into a failure response
    assert r.success is False


def test_claude_code_parses_stdout():
    prov = registry.get_provider("claude_code")
    fake = MagicMock(returncode=0, stdout="  decided  ", stderr="")
    with patch("subprocess.run", return_value=fake):
        assert prov._generate("s", "u", None) == "decided"


def test_claude_code_strips_anthropic_env_from_subprocess(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    prov = registry.get_provider("claude_code")
    fake = MagicMock(returncode=0, stdout="ok", stderr="")
    with patch("subprocess.run", return_value=fake) as mock_run:
        prov._generate("s", "u", None)
    passed_env = mock_run.call_args.kwargs["env"]
    assert "ANTHROPIC_API_KEY" not in passed_env


def test_ollama_parses_response():
    prov = registry.get_provider("ollama")
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"response": '{"action":"NO_TRADE"}'}
    with patch("requests.post", return_value=resp):
        assert prov._generate("s", "u", 128) == '{"action":"NO_TRADE"}'


def test_ollama_unreachable_is_structured_error():
    prov = registry.get_provider("ollama")
    with patch("requests.post", side_effect=OSError("connection refused")):
        with pytest.raises(ProviderError):
            prov._generate("s", "u", None)


# ── the app entry point routes through the abstraction ────────────────────────

def test_agent_ask_claude_routes_through_active_provider():
    import ai.agent as agent
    fake = MagicMock()
    fake.ask.return_value = LLMResponse(True, "ROUTED", "ROUTED", 1, "fake")
    with patch("ai.provider_registry.get_active_provider", return_value=fake):
        assert agent._ask_claude("s", "u") == "ROUTED"
        fake.ask.assert_called_once()


def test_agent_ask_claude_returns_empty_on_failure():
    import ai.agent as agent
    fake = MagicMock()
    fake.ask.return_value = LLMResponse(False, "", "", 1, "fake")
    with patch("ai.provider_registry.get_active_provider", return_value=fake):
        assert agent._ask_claude("s", "u") == ""
