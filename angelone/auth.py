"""
AngelOne SmartAPI authentication.

Flow:
  1. get_angel_client() → SmartConnect session (TOTP-based login)
  2. Session stored in module-level cache; re-created if expired.

Required .env keys:
  ANGEL_API_KEY      - from AngelOne developer portal
  ANGEL_CLIENT_ID    - your AngelOne client/user ID
  ANGEL_PASSWORD     - your login password (PIN)
  ANGEL_TOTP_SECRET  - TOTP secret (from QR code when enabling 2FA)
"""
from __future__ import annotations
import os
import time
import pyotp
from SmartApi import SmartConnect

_client: SmartConnect | None = None
_last_login: float = 0
_SESSION_TTL = 6 * 3600  # re-login every 6 hours


def _env(key: str) -> str:
    val = os.getenv(key, "").strip()
    if not val:
        raise EnvironmentError(f"Missing env var: {key}")
    return val


def get_angel_client() -> SmartConnect:
    """Return a logged-in SmartConnect instance, re-logging if session is stale."""
    global _client, _last_login

    if _client is not None and (time.time() - _last_login) < _SESSION_TTL:
        return _client

    api_key    = _env("ANGEL_API_KEY")
    client_id  = _env("ANGEL_CLIENT_ID")
    password   = _env("ANGEL_PASSWORD")
    totp_secret = _env("ANGEL_TOTP_SECRET")

    totp = pyotp.TOTP(totp_secret).now()

    obj = SmartConnect(api_key=api_key)
    data = obj.generateSession(client_id, password, totp)

    if data.get("status") is False or not data.get("data", {}).get("jwtToken"):
        raise RuntimeError(f"AngelOne login failed: {data.get('message', data)}")

    _client = obj
    _last_login = time.time()
    return _client


def get_profile() -> dict:
    """Return account profile (for sanity-check / connection test)."""
    client = get_angel_client()
    resp = client.getProfile(client.refresh_token)
    if not resp.get("status"):
        raise RuntimeError(f"getProfile failed: {resp}")
    return resp["data"]
