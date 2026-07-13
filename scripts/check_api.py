"""
Quick health check for the Anthropic API key.

Run on the server to confirm the key in .env actually works, using the exact same
key resolution and model the bot uses:

    /root/Ragi_bot/venv/bin/python scripts/check_api.py

It makes one tiny request and prints a clear PASS/FAIL with the specific reason
(missing key, invalid/expired key, wrong model, rate limit, network).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the repo importable when run as `python scripts/check_api.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    try:
        from config import ANTHROPIC_API_KEY  # triggers load_dotenv()
    except Exception as e:
        print(f"FAIL: could not load config/.env ({type(e).__name__}: {e})")
        return 1

    try:
        from ai.agent import CLAUDE_MODEL
    except Exception:
        CLAUDE_MODEL = "claude-sonnet-4-6"

    if not ANTHROPIC_API_KEY:
        print("FAIL: ANTHROPIC_API_KEY is empty/missing in .env")
        print("  → add a valid key:  ANTHROPIC_API_KEY=sk-ant-...")
        return 1

    masked = ANTHROPIC_API_KEY[:10] + "…" + ANTHROPIC_API_KEY[-4:]
    print(f"Key loaded: {masked}  (len={len(ANTHROPIC_API_KEY)})")
    print(f"Model:      {CLAUDE_MODEL}")
    print("Calling Anthropic… (1 tiny request)")

    try:
        from anthropic import Anthropic
    except Exception as e:
        print(f"FAIL: anthropic SDK not installed ({e}). Run: pip install anthropic")
        return 1

    try:
        client = Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=16,
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        print(f"\nPASS ✅  API key works. Model replied: {text!r}")
        print(f"  tokens: in={resp.usage.input_tokens} out={resp.usage.output_tokens}")
        return 0
    except Exception as e:
        name = type(e).__name__
        print(f"\nFAIL ❌  [{name}] {e}")
        if name == "AuthenticationError":
            print("  → the API key is invalid, revoked, or mistyped. Generate a new key")
            print("    at console.anthropic.com and update ANTHROPIC_API_KEY in .env.")
        elif name == "NotFoundError":
            print(f"  → model {CLAUDE_MODEL!r} not available to this key. Set CLAUDE_MODEL in .env.")
        elif name == "PermissionDeniedError":
            print("  → key lacks permission / no credit or billing not set up on the account.")
        elif name == "RateLimitError":
            print("  → rate limited. The key works; wait and retry.")
        elif name in ("APIConnectionError", "APITimeoutError"):
            print("  → network problem reaching api.anthropic.com from this server (egress/firewall).")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
