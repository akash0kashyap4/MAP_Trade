"""
Central authentication for the MAP Trade trading terminal.

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
import hmac
import hashlib

from fastapi import HTTPException, Request
from data.database import save_session, delete_session, get_session

COOKIE_NAME = "map_trade_session"
SESSION_TTL = int(os.getenv("SESSION_TTL_SECONDS", 86400 * 7))  # 7 days default
SESSION_SECRET = os.getenv("SESSION_SECRET", "map_trade_session_fallback_secret_key_12345")


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
        if not raw_pw.startswith("scrypt$"):
            raise RuntimeError(
                "BOT_PASSWORD must be hashed using scrypt (format: scrypt$<salt>$<n>$<r>$<p>$<hash>) when ENV=production."
            )
        if not session_secret_present:
            raise RuntimeError("SESSION_SECRET must be set when ENV=production.")
    return raw_pw or default_password


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    n, r, p = 16384, 8, 1
    h = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p)
    return f"scrypt${salt.hex()}${n}${r}${p}${h.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password.startswith("scrypt$"):
        # Plaintext fallback for development / backward compatibility
        return hmac.compare_digest(plain_password.encode(), hashed_password.encode())
    try:
        parts = hashed_password.split("$")
        if len(parts) != 6:
            return False
        _, salt_hex, n_str, r_str, p_str, hash_hex = parts
        salt = bytes.fromhex(salt_hex)
        n = int(n_str)
        r = int(r_str)
        p = int(p_str)
        target = bytes.fromhex(hash_hex)
        h = hashlib.scrypt(plain_password.encode(), salt=salt, n=n, r=r, p=p)
        return hmac.compare_digest(h, target)
    except Exception:
        return False


def make_token() -> str:
    return secrets.token_urlsafe(48)


def _hash_token(token: str) -> str:
    return hmac.new(SESSION_SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()


async def create_session() -> str:
    """Mint a session token and register it with a TTL. Returns the token."""
    token = make_token()
    hashed = _hash_token(token)
    expiry = time.time() + SESSION_TTL
    await save_session(hashed, expiry)
    return token


async def destroy_session(token: str | None) -> None:
    if token:
        hashed = _hash_token(token)
        await delete_session(hashed)


async def check_session(request: Request) -> bool:
    """True iff the request carries a live (non-expired) session cookie."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return False
    hashed = _hash_token(token)
    expiry = await get_session(hashed)
    if expiry is None or time.time() > expiry:
        if expiry is not None:
            await delete_session(hashed)
        return False
    return True


async def require_user(request: Request) -> None:
    """Dependency: any authenticated session. 401 if missing/expired."""
    if not await check_session(request):
        raise HTTPException(status_code=401, detail="Not authenticated")


async def require_operator(request: Request) -> None:
    """
    Dependency: privileged (trading-control) access.

    Single-operator system today, so every authenticated user is the operator —
    but keeping this distinct from require_user means adding real role checks
    later is a one-function edit rather than a hunt through every handler.
    """
    await require_user(request)
