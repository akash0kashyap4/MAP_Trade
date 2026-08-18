"""Diagnose Groww API auth failures (403 / 401).

Run on the host that actually talks to Groww:

    python scripts/diagnose_groww.py

Reads GROWW_API_KEY / GROWW_SECRET_KEY from the environment (or .env) and
reports what the credential actually is, whether the token exchange works, and
what a real data call returns. Read-only — it never places an order.
"""
from __future__ import annotations
import base64
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _decode(jwt: str) -> dict | None:
    try:
        payload = jwt.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return None


def main() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    api_key = os.getenv("GROWW_API_KEY", "").strip()
    secret = os.getenv("GROWW_SECRET_KEY", "").strip()

    print("=" * 60)
    print("GROWW API DIAGNOSTIC")
    print("=" * 60)

    if not api_key:
        print("FAIL: GROWW_API_KEY is not set.")
        return 1
    print(f"GROWW_API_KEY   : set ({len(api_key)} chars)")
    print(f"GROWW_SECRET_KEY: {'set' if secret else 'NOT SET'}")

    # --- 1. What is this credential? ---
    claims = _decode(api_key)
    if claims:
        now = int(time.time())
        exp = claims.get("exp", 0)
        years = (exp - now) / 31557600
        print("\n[1] Credential claims")
        print(f"    issued : {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(claims.get('iat', 0)))}")
        print(f"    expires: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(exp))}  ({years:.1f} years away)")
        if now >= exp:
            print("    -> EXPIRED. Generate a new key/token in the Groww dashboard.")
            return 1
        sub = claims.get("sub")
        if isinstance(sub, str):
            try:
                sub = json.loads(sub)
            except Exception:
                sub = {}
        if isinstance(sub, dict) and sub.get("role"):
            print(f"    role   : {sub['role']}")
        if years > 1:
            print("    -> This is a long-lived API KEY, not an access token.")
            print("       It must be exchanged before use, or data calls 403.")
        else:
            print("    -> Short expiry: looks like an access token.")
    else:
        print("\n[1] Credential is not a JWT — treating as a plain API key.")

    # --- 2. Exchange ---
    try:
        from growwapi import GrowwAPI
    except ImportError:
        print("\nFAIL: growwapi not installed.  pip install growwapi")
        return 1

    print("\n[2] Token exchange")
    if not secret:
        print("    SKIPPED — no GROWW_SECRET_KEY. Cannot mint an access token.")
        print("    If [1] says this is an API key, this is your 403: set the secret.")
        token = api_key
    else:
        try:
            token = GrowwAPI.get_access_token(api_key=api_key, secret=secret)
            print(f"    OK — access token received ({len(str(token))} chars)")
        except Exception as e:
            print(f"    FAILED: {type(e).__name__}: {e}")
            print("    -> Check the API key and secret are from the SAME Groww app,")
            print("       and that the app is enabled for trading API access.")
            return 1

    # --- 3. Read-only data call ---
    print("\n[3] Live data call (read-only)")
    try:
        client = GrowwAPI(token)
        res = client.get_ltp(
            segment=GrowwAPI.SEGMENT_CASH,
            exchange_trading_symbols=("NSE_NIFTY",),
        )
        print(f"    OK — {res}")
        print("\nRESULT: Groww API is working.")
        return 0
    except Exception as e:
        name = type(e).__name__
        print(f"    FAILED: {name}: {e}")
        if "Authorisation" in name or "403" in str(e):
            print("\n    403 = the credential is valid but lacks permission.")
            print("    Usual causes:")
            print("      - the API key was used directly instead of an access token")
            print("      - the Groww app has no market-data / trading subscription")
            print("      - the key was revoked or regenerated in the dashboard")
        elif "Authentication" in name or "401" in str(e):
            print("\n    401 = token expired or invalid. Regenerate it.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
