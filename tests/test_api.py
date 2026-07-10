from __future__ import annotations

from fastapi.testclient import TestClient

from main import app
import config
from data.store import store


client = TestClient(app)


def test_get_risk_config_endpoint():
    response = client.get("/api/config/risk")
    assert response.status_code == 200
    data = response.json()

    assert data["paper_trade"] == config.TRADING["paper_trade"]
    assert data["lots"] == config.TRADING["lots"]
    assert "max_daily_loss" in data
    assert "bot_paused" in data
    assert "new_entries_enabled" in data


def test_override_square_off_endpoint(monkeypatch):
    class DummyTrader:
        async def emergency_square_off(self):
            return 3

    app.state.trader = DummyTrader()

    response = client.post("/api/override/square-off")
    assert response.status_code == 200
    data = response.json()
    assert data == {"ok": True, "closed_count": 3, "bot_paused": True}


def test_override_state_endpoint():
    response = client.post("/api/override/state", json={"paused": True, "new_entries_enabled": False})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["bot_paused"] is True
    assert data["new_entries_enabled"] is False

    response = client.post("/api/override/state", json={"paused": False, "new_entries_enabled": True})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["bot_paused"] is False
    assert data["new_entries_enabled"] is True
