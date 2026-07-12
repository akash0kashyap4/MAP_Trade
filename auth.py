"""
Central authentication for the Ragi trading terminal.

Lives in its own module (not main.py) so routers can depend on it without the
circular import that previously forced `from main import require_auth` to be
written inside every handler body. Sessions are opaque random tokens kept in an
in-memory dict keyed to an expiry timestamp — correct for this single-operator,
single-process deployment. If the app is ever run with more than one worker, or
sessions must survive a restart, replace `_sessions` with a shared store
(Redis / signed cookies) — see docs/REMEDIATION_BLUEPRINT.md §14.
"""
from __future__ import annotations
import os
import secrets
import time

from fastapi import HTTPException, Request

COOKIE_NAME = "ragi_session"
SESSION_TTL = int(os.getenv("SESSION_TTL_SECONDS", 86400 * 7))  # 7 days default

# token -> expiry epoch seconds
_sessions: dict[str, float] = {}


DEFAULT_PASSWORD = "ChangeMe123!"


def resolve_bot_password(
    raw_pw: str | None,
    is_production: bool,
    session_secret_present: bool,
    default_password: str = DEFAULT_PASSWORD,
) -> str:
    """Resolve the effective bot password, refusing weak config in production.

    Pure function (no env/global reads) so the launch-blocking behavior is unit
    testable. In production an unset or default password, or a missing
    SESSION_SECRET, is a hard boot failure rather than a warning.
    """
    if is_production:
        if not raw_pw or raw_pw == default_password:
            raise RuntimeError(
                "BOT_PASSWORD must be set to a strong, non-default value when ENV=production."
            )
        if not session_secret_present:
            raise RuntimeError("SESSION_SECRET must be set when ENV=production.")
    return raw_pw or default_password


def make_token() -> str:
    return secrets.token_urlsafe(48)


def create_session() -> str:
    """Mint a session token and register it with a TTL. Returns the token."""
    token = make_token()
    _sessions[token] = time.time() + SESSION_TTL
    return token


def destroy_session(token: str | None) -> None:
    if token:
        _sessions.pop(token, None)


def check_session(request: Request) -> bool:
    """True iff the request carries a live (non-expired) session cookie."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return False
    expiry = _sessions.get(token)
    if expiry is None or time.time() > expiry:
        _sessions.pop(token, None)
        return False
    return True


def require_user(request: Request) -> None:
    """Dependency: any authenticated session. 401 if missing/expired."""
    if not check_session(request):
        raise HTTPException(status_code=401, detail="Not authenticated")


def require_operator(request: Request) -> None:
    """
    Dependency: privileged (trading-control) access.

    Single-operator system today, so every authenticated user is the operator —
    but keeping this distinct from require_user means adding real role checks
    later is a one-function edit rather than a hunt through every handler.
    """
    require_user(request)
