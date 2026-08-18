from __future__ import annotations
from growwapi import GrowwAPI
from config import GROWW_API_KEY, GROWW_SECRET_KEY

_groww_client: GrowwAPI | None = None


def get_groww_client() -> GrowwAPI:
    """
    Returns a cached GrowwAPI client authenticated with a real access token.

    A Groww API key is itself a JWT, so "starts with eyJ" says nothing about
    whether it is an access token — the long-lived API key and the short-lived
    access token both look identical at a glance. Data endpoints only accept the
    access token: handing them the raw API key is accepted as a *valid*
    credential but refused as unauthorised, which surfaces as HTTP 403
    (GrowwAPIAuthorisationException, "token does not have the required
    permissions") rather than the 401 you would get from an expired token.

    So whenever a secret is configured we always exchange the API key for an
    access token. Only when no secret exists do we assume the value really is a
    ready-made access token.
    """
    global _groww_client

    if _groww_client is not None:
        return _groww_client

    if not GROWW_API_KEY:
        raise ValueError("GROWW_API_KEY not set in .env")

    if GROWW_SECRET_KEY:
        print("[groww.auth] Exchanging API key + secret for an access token...")
        access_token = GrowwAPI.get_access_token(
            api_key=GROWW_API_KEY,
            secret=GROWW_SECRET_KEY,
        )
        _groww_client = GrowwAPI(access_token)
    else:
        # No secret to exchange with — treat the value as an access token and
        # let Groww be the judge. A 403 here means it was an API key after all.
        print("[groww.auth] No GROWW_SECRET_KEY set — using GROWW_API_KEY as a "
              "direct access token")
        _groww_client = GrowwAPI(GROWW_API_KEY)

    print("[groww.auth] Groww client ready")
    return _groww_client


def reset_client():
    """Force re-authentication on next call (e.g. after token expiry)."""
    global _groww_client
    _groww_client = None
