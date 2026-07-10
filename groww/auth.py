from __future__ import annotations
from growwapi import GrowwAPI
from config import GROWW_API_KEY, GROWW_SECRET_KEY

_groww_client: GrowwAPI | None = None


def get_groww_client() -> GrowwAPI:
    """
    Returns a cached GrowwAPI client.

    Strategy:
    1. If GROWW_API_KEY looks like a JWT (starts with 'eyJ'), use it directly
       as the access_token — no need to call get_access_token() at all.
    2. Otherwise, call get_access_token() once and cache the result.

    This avoids hammering the token endpoint and hitting rate limits.
    """
    global _groww_client

    if _groww_client is not None:
        return _groww_client

    if not GROWW_API_KEY:
        raise ValueError("GROWW_API_KEY not set in .env")

    # If the key is already a JWT access token, use it directly
    if GROWW_API_KEY.startswith("eyJ"):
        print("[groww.auth] Using GROWW_API_KEY as direct access token (JWT detected)")
        _groww_client = GrowwAPI(GROWW_API_KEY)
    else:
        # It's an API key — exchange for access token (called only once)
        if not GROWW_SECRET_KEY:
            raise ValueError("GROWW_SECRET_KEY not set in .env")
        print("[groww.auth] Exchanging API key for access token...")
        access_token = GrowwAPI.get_access_token(
            api_key=GROWW_API_KEY,
            secret=GROWW_SECRET_KEY,
        )
        _groww_client = GrowwAPI(access_token)

    print("[groww.auth] Groww client ready")
    return _groww_client


def reset_client():
    """Force re-authentication on next call (e.g. after token expiry)."""
    global _groww_client
    _groww_client = None
