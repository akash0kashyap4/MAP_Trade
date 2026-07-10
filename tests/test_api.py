"""Unit tests for API endpoint logic: /api/config/risk, /api/override/state, /api/override/square-off."""
from __future__ import annotations

import pytest

import config
from data.store import LiveStore


def _risk_payload(s: LiveStore) -> dict:
    t = config.TRADING
    return {
        "paper_trade":         t.get("paper_trade", True),
        "lots":                t.get("lots", 1),
        "max_positions":       t.get("max_positions", 2),
        "max_daily_loss":      t.get("max_daily_loss", 5000),
        "fallback_sl_pct":     t.get("fallback_sl_pct", 0.30),
        "fallback_target_pct": t.get("fallback_target_pct", 0.60),
        "trailing_sl_trigger": t.get("trailing_sl_trigger", 0.40),
        "trailing_sl_step":    t.get("trailing_sl_step", 0.20),
        "min_confidence":      t.get("min_confidence", 1),
        "bot_paused":          s.bot_paused,
        "new_entries_enabled": s.new_entries_enabled,
    }


class TestRiskConfigPayload:
    def setup_method(self):
        self.store = LiveStore()

    def test_has_required_keys(self):
        payload = _risk_payload(self.store)
        for key in ("paper_trade", "lots", "max_positions", "max_daily_loss",
                    "fallback_sl_pct", "fallback_target_pct", "bot_paused", "new_entries_enabled"):
            assert key in payload

    def test_bot_paused_default_false(self):
        assert _risk_payload(self.store)["bot_paused"] is False

    def test_new_entries_default_true(self):
        assert _risk_payload(self.store)["new_entries_enabled"] is True

    def test_reflects_store_state(self):
        self.store.bot_paused = True
        self.store.new_entries_enabled = False
        p = _risk_payload(self.store)
        assert p["bot_paused"] is True
        assert p["new_entries_enabled"] is False

    def test_lots_positive(self):
        assert _risk_payload(self.store)["lots"] > 0

    def test_max_daily_loss_positive(self):
        assert _risk_payload(self.store)["max_daily_loss"] > 0


class TestOverrideStateUnit:
    def setup_method(self):
        self.store = LiveStore()

    def _apply(self, paused=None, new_entries=None):
        changed = {}
        if paused is not None:
            self.store.bot_paused = paused
            changed["bot_paused"] = self.store.bot_paused
        if new_entries is not None:
            self.store.new_entries_enabled = new_entries
            changed["new_entries_enabled"] = self.store.new_entries_enabled
        return changed

    def test_pause_bot(self):
        result = self._apply(paused=True)
        assert result["bot_paused"] is True
        assert self.store.bot_paused is True

    def test_resume_bot(self):
        self.store.bot_paused = True
        result = self._apply(paused=False)
        assert result["bot_paused"] is False

    def test_disable_entries(self):
        result = self._apply(new_entries=False)
        assert result["new_entries_enabled"] is False
        assert self.store.new_entries_enabled is False

    def test_enable_entries(self):
        self.store.new_entries_enabled = False
        result = self._apply(new_entries=True)
        assert result["new_entries_enabled"] is True

    def test_empty_body_returns_nothing(self):
        assert self._apply() == {}

    def test_both_fields_at_once(self):
        result = self._apply(paused=True, new_entries=False)
        assert result["bot_paused"] is True
        assert result["new_entries_enabled"] is False


def _square_off_all(s: LiveStore) -> dict:
    positions_snapshot = list(s.positions)
    if not positions_snapshot:
        s.bot_paused = True
        return {"ok": True, "closed": 0, "total_pnl": 0.0, "positions": [], "errors": [], "bot_paused": True}

    closed = []
    errors = []
    for pos in positions_snapshot:
        try:
            ltp  = pos.get("ltp") or pos.get("entry", 0.0)
            qty  = pos.get("quantity", 0)
            pnl  = round((ltp - pos["entry"]) * qty, 2)
            s.realized_pnl   = round(s.realized_pnl + pnl, 2)
            s.cumulative_pnl = round(s.cumulative_pnl + pnl, 2)
            s.remove_position(pos["instrument"], pos["strike"], pos["type"])
            closed.append({"instrument": pos["instrument"], "pnl": pnl})
        except Exception as e:
            errors.append(str(e))

    s.bot_paused = True
    total_pnl = sum(c["pnl"] for c in closed)
    return {"ok": True, "closed": len(closed), "total_pnl": round(total_pnl, 2),
            "positions": closed, "errors": errors, "bot_paused": True}


class TestEmergencySquareOffUnit:
    def setup_method(self):
        self.store = LiveStore()

    def test_no_positions_returns_zero_closed(self):
        result = _square_off_all(self.store)
        assert result["closed"] == 0
        assert result["bot_paused"] is True

    def test_pauses_bot_even_when_empty(self):
        _square_off_all(self.store)
        assert self.store.bot_paused is True

    def test_closes_single_position(self):
        self.store.add_position({
            "instrument": "NIFTY", "strike": 24000, "type": "CE",
            "entry": 100.0, "ltp": 120.0, "quantity": 75, "pnl": 1500.0,
        })
        result = _square_off_all(self.store)
        assert result["closed"] == 1
        assert result["total_pnl"] == pytest.approx(1500.0, abs=1)
        assert len(self.store.positions) == 0

    def test_closes_multiple_positions(self):
        for strike, entry, ltp, qty in [(24000, 100.0, 90.0, 75), (48000, 200.0, 250.0, 30)]:
            self.store.add_position({
                "instrument": "NIFTY" if qty == 75 else "BANKNIFTY",
                "strike": strike, "type": "CE",
                "entry": entry, "ltp": ltp, "quantity": qty, "pnl": 0,
            })
        result = _square_off_all(self.store)
        assert result["closed"] == 2
        assert len(self.store.positions) == 0

    def test_realized_pnl_updated(self):
        self.store.add_position({
            "instrument": "NIFTY", "strike": 24000, "type": "CE",
            "entry": 100.0, "ltp": 130.0, "quantity": 65, "pnl": 0,
        })
        _square_off_all(self.store)
        assert self.store.realized_pnl == pytest.approx(1950.0, abs=1)

    def test_sse_payload_includes_override_flags(self):
        s = LiveStore()
        s.bot_paused = True
        s.new_entries_enabled = False
        payload = s.sse_payload()
        assert payload["bot_paused"] is True
        assert payload["new_entries"] is False
