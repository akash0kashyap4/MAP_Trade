"""Tests for LAN monitoring features: health endpoints, startup banner, LAN IP detection."""
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_get_lan_ip_returns_string():
    from main import _get_lan_ip
    ip = _get_lan_ip()
    assert isinstance(ip, str)
    parts = ip.split(".")
    assert len(parts) == 4, f"Expected IPv4, got {ip}"
    for part in parts:
        assert part.isdigit()


def test_print_startup_banner(capsys):
    from main import _print_startup_banner
    _print_startup_banner("0.0.0.0", 8000)
    out = capsys.readouterr().out
    assert "Server:    0.0.0.0:8000" in out
    assert "Dashboard: http://" in out
    assert ":8000" in out
    assert "Health:" in out
    assert "PAPER" in out


def test_print_startup_banner_custom_port(capsys):
    from main import _print_startup_banner
    _print_startup_banner("0.0.0.0", 9090)
    out = capsys.readouterr().out
    assert ":9090" in out


def test_health_endpoint():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["service"] == "map-trade"


def test_health_detailed_endpoint():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    r = client.get("/health/detailed")
    assert r.status_code == 200
    data = r.json()
    required_fields = [
        "status", "trading_mode", "bot_paused", "feed_status",
        "ai_status", "positions_open", "last_tick", "db",
        "llm_provider", "llm_available", "scheduler",
    ]
    for field in required_fields:
        assert field in data, f"Missing field: {field}"


def test_health_detailed_no_auth_required():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    r = client.get("/health/detailed")
    assert r.status_code == 200


def test_health_detailed_trading_mode():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    r = client.get("/health/detailed")
    data = r.json()
    assert data["trading_mode"] in ("paper", "live")


def test_config_app_host():
    from config import APP_HOST
    assert APP_HOST == os.getenv("APP_HOST", "0.0.0.0")


def test_config_app_port():
    from config import APP_PORT
    assert isinstance(APP_PORT, int)
    assert 1 <= APP_PORT <= 65535


def test_config_default_paper_mode():
    from config import TRADING
    if os.getenv("TRADING_MODE", "paper") != "live":
        assert TRADING["paper_trade"] is True


def test_dashboard_unauthenticated_redirects():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code in (302, 307)


def test_root_serves_login_page():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
