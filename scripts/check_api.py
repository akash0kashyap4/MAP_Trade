"""
Quick health check for the AI-brain provider (Anthropic API, Claude Code CLI,
Copilot CLI, Ollama, or a fallback chain of these).

Run on the server to confirm the configured provider + key actually work, using
the bot's exact code path:

    /root/Ragi_bot/venv/bin/python scripts/check_api.py

It makes one tiny request through the same dispatcher the bot uses and prints a
clear PASS/FAIL. Set AI_PROVIDER in .env to choose the provider (see .env.example).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    try:
        import config
    except Exception as e:
        print(f"FAIL: could not load config/.env ({type(e).__name__}: {e})")
        return 1

    provider = getattr(config, "AI_PROVIDER", "claude")
    from ai.agent import CLAUDE_MODEL
    key, key_name, model = config.ANTHROPIC_API_KEY, "ANTHROPIC_API_KEY", CLAUDE_MODEL

    print(f"Provider:   {provider}")
    print(f"Model:      {model}")
    if not key:
        print(f"FAIL: {key_name} is empty/missing in .env (AI_PROVIDER={provider})")
        return 1
    print(f"Key loaded: {key[:8]}…{key[-4:]}  (len={len(key)})")
    print("Calling the AI brain… (1 tiny request through the bot's own code path)")

    from ai.agent import _ask_claude  # the provider dispatcher
    text = _ask_claude("You are a test.", "Reply with exactly: OK", max_retries=1, max_tokens=16)

    if text and "OK" in text.upper():
        print(f"\nPASS ✅  {provider} works. Model replied: {text.strip()!r}")
        return 0
    if text:
        print(f"\nPASS ✅  {provider} responded (unexpected text): {text.strip()[:80]!r}")
        return 0
    print(f"\nFAIL ❌  {provider} returned nothing. See the [agent] error lines above for the")
    print(f"   reason (bad/expired {key_name}, wrong model, no credit/quota, rate limit, or network).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
