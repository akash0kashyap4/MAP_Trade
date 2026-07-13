"""Tests for the pluggable AI-brain provider (Claude vs Gemini)."""
from unittest.mock import MagicMock, patch

import ai.agent as agent


def test_dispatch_routes_to_gemini(monkeypatch):
    monkeypatch.setattr("config.AI_PROVIDER", "gemini", raising=False)
    with patch.object(agent, "_ask_gemini", return_value="GEM") as g, \
         patch.object(agent, "_ask_anthropic", return_value="CLA") as c:
        assert agent._ask_claude("s", "u") == "GEM"
        g.assert_called_once()
        c.assert_not_called()


def test_dispatch_routes_to_claude_by_default(monkeypatch):
    monkeypatch.setattr("config.AI_PROVIDER", "claude", raising=False)
    with patch.object(agent, "_ask_gemini", return_value="GEM") as g, \
         patch.object(agent, "_ask_anthropic", return_value="CLA") as c:
        assert agent._ask_claude("s", "u") == "CLA"
        c.assert_called_once()
        g.assert_not_called()


def test_gemini_missing_key_returns_empty(monkeypatch):
    monkeypatch.setattr("config.GEMINI_API_KEY", "", raising=False)
    assert agent._ask_gemini("s", "u", max_retries=0) == ""


def test_gemini_parses_successful_response(monkeypatch):
    monkeypatch.setattr("config.GEMINI_API_KEY", "test-key", raising=False)
    monkeypatch.setattr("config.GEMINI_MODEL", "gemini-2.0-flash", raising=False)

    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "candidates": [{
            "finishReason": "STOP",
            "content": {"parts": [{"text": '{"action": "NO_TRADE"}'}]},
        }]
    }
    with patch("requests.post", return_value=resp) as post:
        out = agent._ask_gemini("system", "user", max_retries=0, max_tokens=256)
    assert out == '{"action": "NO_TRADE"}'
    # system prompt goes in system_instruction, user text in contents
    body = post.call_args.kwargs["json"]
    assert body["system_instruction"]["parts"][0]["text"] == "system"
    assert body["contents"][0]["parts"][0]["text"] == "user"
    assert body["generationConfig"]["maxOutputTokens"] == 256


def test_gemini_http_error_returns_empty(monkeypatch):
    monkeypatch.setattr("config.GEMINI_API_KEY", "test-key", raising=False)
    resp = MagicMock()
    resp.status_code = 429  # free-tier rate limit
    resp.text = "quota exceeded"
    with patch("requests.post", return_value=resp):
        assert agent._ask_gemini("s", "u", max_retries=0) == ""
