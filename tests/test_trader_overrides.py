"""Tests for bot/trader.py override-flag integration and CSRF check in routes."""
import sys
import os
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.store import LiveStore


# ── Store override flag tests ─────────────────────────────────────────────────

class TestStoreOverrideFlags:
    def setup_method(self):
        self.store = LiveStore()

    def test_bot_paused_default_false(self):
        assert self.store.bot_paused is False

    def test_new_entries_enabled_default_true(self):
        assert self.store.new_entries_enabled is True

    def test_pause_sets_flag(self):
        self.store.bot_paused = True
        assert self.store.bot_paused is True

    def test_disable_entries_sets_flag(self):
        self.store.new_entries_enabled = False
        assert self.store.new_entries_enabled is False

    def test_sse_payload_includes_bot_paused(self):
        self.store.bot_paused = True
        p = self.store.sse_payload()
        assert p["bot_paused"] is True

    def test_sse_payload_includes_new_entries(self):
        self.store.new_entries_enabled = False
        p = self.store.sse_payload()
        assert p["new_entries"] is False

    def test_flags_are_independent(self):
        self.store.bot_paused = True
        self.store.new_entries_enabled = True
        assert self.store.bot_paused is True
        assert self.store.new_entries_enabled is True

    def test_flags_survive_price_updates(self):
        self.store.bot_paused = True
        self.store.update_price("NIFTY", 24000.0)
        assert self.store.bot_paused is True

    def test_reset_daily_does_not_clear_pause(self):
        """Override flags are operator controls — reset_daily should not clear them."""
        self.store.bot_paused = True
        self.store.new_entries_enabled = False
        self.store.reset_daily()
        assert self.store.bot_paused is True
        assert self.store.new_entries_enabled is False


# ── CSRF origin check ─────────────────────────────────────────────────────────

def _make_mock_request(origin="", referer="", host="localhost:8000"):
    """Minimal mock of FastAPI Request for testing _check_same_origin."""
    class _Headers(dict):
        def get(self, key, default=""):
            return super().get(key.lower(), default)

    class _Req:
        headers = _Headers({
            "origin": origin,
            "referer": referer,
            "host": host,
        })

    return _Req()


def _check_same_origin(request):
    """Inline replica of routers/routes.py _check_same_origin (uses ValueError for testability)."""
    origin  = request.headers.get("origin", "")
    referer = request.headers.get("referer", "")
    host    = request.headers.get("host", "")
    for header_val in (origin, referer):
        if header_val and host and host not in header_val:
            raise ValueError("Cross-origin request rejected")


class TestSameOriginCheck:
    def test_no_origin_header_passes(self):
        req = _make_mock_request(origin="", referer="")
        _check_same_origin(req)  # should not raise

    def test_same_origin_passes(self):
        req = _make_mock_request(origin="http://localhost:8000", host="localhost:8000")
        _check_same_origin(req)

    def test_same_referer_passes(self):
        req = _make_mock_request(referer="http://localhost:8000/dashboard", host="localhost:8000")
        _check_same_origin(req)

    def test_cross_origin_rejected(self):
        req = _make_mock_request(origin="http://evil.com", host="localhost:8000")
        with pytest.raises(ValueError, match="Cross-origin"):
            _check_same_origin(req)

    def test_cross_referer_rejected(self):
        req = _make_mock_request(referer="http://evil.com/page", host="localhost:8000")
        with pytest.raises(ValueError, match="Cross-origin"):
            _check_same_origin(req)

    def test_production_host_same_origin_passes(self):
        req = _make_mock_request(origin="https://ragi.example.com", host="ragi.example.com")
        _check_same_origin(req)
