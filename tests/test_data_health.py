"""Tests for data/health.py — data-layer circuit breaker + degradation alerting.

Covers: circuit trip/close thresholds, single-alert-per-transition (no spam),
serving-mock degradation, snapshot shape, and the headline scenario the rubric
demands — NSE + Groww both failing must degrade the layer, alert once, and NOT
report a healthy/live status.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.health import DataHealth, FAILURE_THRESHOLD, CRITICAL_SOURCES


def _tracker():
    """A DataHealth with a captured alert list and a controllable clock."""
    alerts = []
    clk = {"t": 1000.0}
    dh = DataHealth(clock=lambda: clk["t"], alert_sink=alerts.append)
    return dh, alerts, clk


class TestCircuitBreaker:
    def test_single_failure_does_not_open(self):
        dh, alerts, _ = _tracker()
        dh.record_failure("groww_chain", "boom")
        assert dh.degraded is False
        assert alerts == []

    def test_opens_at_threshold(self):
        dh, alerts, _ = _tracker()
        for _ in range(FAILURE_THRESHOLD):
            dh.record_failure("groww_chain", "boom")
        assert dh.degraded is True
        snap = dh.snapshot()
        assert "groww_chain" in snap["open_sources"]
        assert snap["status"] == "degraded"

    def test_success_closes_circuit(self):
        dh, alerts, _ = _tracker()
        for _ in range(FAILURE_THRESHOLD):
            dh.record_failure("feed", "down")
        assert dh.degraded is True
        dh.record_success("feed")
        assert dh.degraded is False
        assert dh.snapshot()["status"] == "healthy"

    def test_non_critical_source_does_not_degrade(self):
        dh, alerts, _ = _tracker()
        assert "some_optional_source" not in CRITICAL_SOURCES
        for _ in range(FAILURE_THRESHOLD + 2):
            dh.record_failure("some_optional_source", "meh")
        # A non-critical source opening must not mark the whole layer degraded.
        assert dh.degraded is False


class TestAlerting:
    def test_alert_fires_once_on_degrade(self):
        dh, alerts, _ = _tracker()
        for _ in range(FAILURE_THRESHOLD + 5):
            dh.record_failure("nse_chain", "403")
        # Many failures, but only ONE degrade alert (no per-tick spam).
        degrade_alerts = [a for a in alerts if "DEGRADED" in a]
        assert len(degrade_alerts) == 1

    def test_recovery_alert_fires_once(self):
        dh, alerts, _ = _tracker()
        for _ in range(FAILURE_THRESHOLD):
            dh.record_failure("feed", "down")
        dh.record_success("feed")
        recovery = [a for a in alerts if "RECOVERED" in a]
        assert len(recovery) == 1

    def test_alert_sink_exception_does_not_crash(self):
        def bad_sink(_msg):
            raise RuntimeError("telegram down")
        dh = DataHealth(alert_sink=bad_sink)
        # Must not raise even though the sink throws.
        for _ in range(FAILURE_THRESHOLD):
            dh.record_failure("feed", "x")
        assert dh.degraded is True


class TestServingMock:
    def test_serving_mock_degrades_and_recovers(self):
        dh, alerts, _ = _tracker()
        dh.set_serving_mock(True)
        assert dh.degraded is True
        assert dh.snapshot()["serving_mock"] is True
        dh.set_serving_mock(False)
        assert dh.degraded is False


class TestBothSourcesFailScenario:
    """Rubric acceptance check: NSE + Groww both failing must degrade the layer,
    alert once, and never report healthy/live while serving mock."""

    def test_nse_and_groww_both_down_degrades_and_alerts(self):
        dh, alerts, _ = _tracker()
        # Simulate the real fallback chain collapsing: groww options/chain fail,
        # NSE fails, and the app falls back to mock.
        for _ in range(FAILURE_THRESHOLD):
            dh.record_failure("groww_chain", "token expired")
        for _ in range(FAILURE_THRESHOLD):
            dh.record_failure("nse_chain", "connection reset")
        dh.set_serving_mock(True)

        snap = dh.snapshot()
        # Degraded, not healthy, not silently "live".
        assert snap["status"] == "degraded"
        assert snap["degraded"] is True
        assert snap["serving_mock"] is True
        assert "groww_chain" in snap["open_sources"]
        assert "nse_chain" in snap["open_sources"]
        # Exactly one operator alert was raised (not one per failed call).
        assert len([a for a in alerts if "DEGRADED" in a]) == 1

    def test_recovery_after_both_down(self):
        dh, alerts, _ = _tracker()
        for _ in range(FAILURE_THRESHOLD):
            dh.record_failure("groww_chain", "x")
        for _ in range(FAILURE_THRESHOLD):
            dh.record_failure("nse_chain", "y")
        dh.set_serving_mock(True)
        assert dh.degraded is True
        # Partial recovery is NOT full recovery: clearing mock + one source
        # while the other circuit is still open must stay degraded.
        dh.record_success("nse_chain")
        dh.set_serving_mock(False)
        assert dh.degraded is True, "still degraded while groww_chain circuit is open"
        # Both live sources back → healthy.
        dh.record_success("groww_chain")
        assert dh.degraded is False
        assert dh.snapshot()["status"] == "healthy"


class TestSnapshotShape:
    def test_snapshot_has_expected_keys(self):
        dh, _, _ = _tracker()
        dh.record_success("feed")
        dh.record_failure("groww_chain", "boom")
        snap = dh.snapshot()
        for key in ("degraded", "serving_mock", "status", "open_sources", "sources"):
            assert key in snap
        assert "feed" in snap["sources"]
        assert snap["sources"]["feed"]["total_successes"] == 1
        assert snap["sources"]["groww_chain"]["total_failures"] == 1
