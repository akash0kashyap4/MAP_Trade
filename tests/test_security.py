"""
HTTP-level security tests for the Ragi trading terminal.

Unlike the older suites that call route functions directly, these drive the real
FastAPI app through Starlette's TestClient so routing, the router-level auth
dependency, and middleware are actually exercised — the layer where the audit's
open-API-surface findings live. Requests are made WITHOUT entering the client as
a context manager, so the heavy lifespan (DB, scheduler, live feed) does not run;
the anonymous-denied paths reject before any app.state access.
"""

import pytest

# Skip cleanly if FastAPI/TestClient aren't the real thing (e.g. stubbed env).
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import main  # noqa: E402

client = TestClient(main.app)


# Every /api/* route + /stream that must reject anonymous callers.
SENSITIVE_GET = [
    "/api/status", "/api/trades/today", "/api/trades", "/api/rules",
    "/api/config/risk", "/api/trading/mode", "/api/positions", "/api/pnl",
    "/api/backtest/status", "/api/data/cache/stats",
]
SENSITIVE_POST = [
    "/api/override/state", "/api/override/square-off", "/api/trading/set-mode",
    "/api/backtest/run", "/api/backtest/run-all", "/api/data/download",
    "/api/learn/run-now", "/api/trades/import",
]


@pytest.mark.parametrize("path", SENSITIVE_GET)
def test_anonymous_get_denied(path):
    assert client.get(path).status_code == 401, f"{path} must reject anonymous GET"


@pytest.mark.parametrize("path", SENSITIVE_POST)
def test_anonymous_post_denied(path):
    # 401 before body validation: auth is a router-level dependency, so even a
    # malformed/empty body must not slip past as a 422.
    assert client.post(path, json={}).status_code == 401, f"{path} must reject anonymous POST"


def test_anonymous_sse_denied():
    r = client.get("/stream")
    assert r.status_code == 401, "SSE stream must reject anonymous clients before streaming"


def test_login_is_post_only():
    # A GET-able login form would leak credentials into URLs/history/logs.
    assert client.get("/api/login").status_code == 405


def test_logout_is_post_only():
    assert client.get("/api/logout").status_code == 405


def test_health_is_public():
    assert client.get("/health").status_code == 200


def test_robots_disallows_all():
    r = client.get("/robots.txt")
    assert r.status_code == 200
    assert "Disallow: /" in r.text


def test_security_headers_present():
    h = client.get("/health").headers
    assert h.get("x-content-type-options") == "nosniff"
    assert h.get("referrer-policy") == "no-referrer"
    assert h.get("x-frame-options") == "DENY"
    assert "frame-ancestors 'none'" in h.get("content-security-policy", "")


def test_authenticated_request_passes(monkeypatch):
    """A valid session cookie gets past the gate (no 401)."""
    token = auth.create_session()
    authed = TestClient(main.app, cookies={auth.COOKIE_NAME: token})
    try:
        r = authed.get("/api/status")
        assert r.status_code != 401
    finally:
        auth.destroy_session(token)


def test_no_duplicate_route_registrations():
    """Guards against the duplicate-handler bug where a second registration
    silently shadows the first (how the dead square-off handler survived)."""
    seen = set()
    dupes = []
    for route in main.app.routes:
        path = getattr(route, "path", None)
        if path is None:
            continue  # mounts / included routers without a concrete path
        for m in (getattr(route, "methods", None) or {"GET"}):
            key = (m, path)
            if key in seen:
                dupes.append(key)
            seen.add(key)
    assert not dupes, f"duplicate route registrations: {dupes}"


# ── Production-config hard-fail (pure-function, no app import needed) ──────────

def test_production_refuses_default_password():
    with pytest.raises(RuntimeError):
        auth.resolve_bot_password(auth.DEFAULT_PASSWORD, is_production=True,
                                  session_secret_present=True)


def test_production_refuses_missing_password():
    with pytest.raises(RuntimeError):
        auth.resolve_bot_password(None, is_production=True,
                                  session_secret_present=True)


def test_production_requires_session_secret():
    with pytest.raises(RuntimeError):
        auth.resolve_bot_password("a-strong-password", is_production=True,
                                  session_secret_present=False)


def test_production_accepts_strong_config():
    assert auth.resolve_bot_password("a-strong-password", is_production=True,
                                     session_secret_present=True) == "a-strong-password"


def test_development_allows_default():
    assert auth.resolve_bot_password(None, is_production=False,
                                     session_secret_present=False) == auth.DEFAULT_PASSWORD


def test_docs_disabled_flag_matches_env():
    """In this (development) test run docs are enabled; the app wires docs_url to
    None only when IS_PRODUCTION. Assert the wiring is live, not hard-coded on."""
    from config import IS_PRODUCTION
    if IS_PRODUCTION:
        assert main.app.docs_url is None and main.app.openapi_url is None
    else:
        assert main.app.docs_url == "/docs" and main.app.openapi_url == "/openapi.json"
