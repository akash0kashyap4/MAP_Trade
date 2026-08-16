"""
Data-layer circuit breaker + degradation alerting.

The bot pulls market data from unofficial NSE and Groww endpoints with a
mock generator as last resort. Before this module, each fallback set a scattered
`using_mock_*` flag silently — so the system could serve mock/stale data while
the dashboard still read "live". This centralises that into an honest, alertable
health model:

  - Each data source (feed, groww_chain, groww_options, nse_chain, ...) is a
    circuit with a rolling consecutive-failure count.
  - After `FAILURE_THRESHOLD` consecutive failures a circuit trips OPEN; the
    next success closes it.
  - The layer is DEGRADED when any *critical* source is open, or when the app
    is serving mock data. Degraded state is exposed to the UI and, on the
    healthy→degraded and degraded→healthy transitions only, fires a single
    alert (Telegram) — never spamming per tick.

The module is deliberately dependency-free and clock/alert-injectable so it can
be unit-tested deterministically (see tests/test_data_health.py).
"""
from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable, Optional

# Consecutive failures before a circuit trips open.
FAILURE_THRESHOLD = 3

# Sources whose outage means "we are NOT getting real market data". A mock
# fallback on any of these is a degradation the operator must know about.
CRITICAL_SOURCES = frozenset({"feed", "groww_chain", "groww_options", "nse_chain"})


@dataclass
class _Circuit:
    name: str
    consecutive_failures: int = 0
    total_failures: int = 0
    total_successes: int = 0
    last_ok_ts: Optional[float] = None
    last_fail_ts: Optional[float] = None
    last_error: str = ""

    def is_open(self, threshold: int = FAILURE_THRESHOLD) -> bool:
        return self.consecutive_failures >= threshold


@dataclass
class DataHealth:
    """Tracks per-source data health and fires one alert per state transition."""

    clock: Callable[[], float] = _time.time
    alert_sink: Optional[Callable[[str], None]] = None
    threshold: int = FAILURE_THRESHOLD
    _circuits: dict[str, _Circuit] = field(default_factory=dict)
    _degraded: bool = False
    _serving_mock: bool = False
    _lock: Lock = field(default_factory=Lock)

    # ── recording ──────────────────────────────────────────────────────────
    def _circuit(self, source: str) -> _Circuit:
        c = self._circuits.get(source)
        if c is None:
            c = _Circuit(name=source)
            self._circuits[source] = c
        return c

    def record_success(self, source: str) -> None:
        with self._lock:
            c = self._circuit(source)
            c.consecutive_failures = 0
            c.total_successes += 1
            c.last_ok_ts = self.clock()
            c.last_error = ""
            self._recompute_locked()

    def record_failure(self, source: str, error: str = "") -> None:
        with self._lock:
            c = self._circuit(source)
            c.consecutive_failures += 1
            c.total_failures += 1
            c.last_fail_ts = self.clock()
            if error:
                c.last_error = str(error)[:200]
            self._recompute_locked()

    def set_serving_mock(self, value: bool) -> None:
        """Explicit signal that the app is currently returning mock data."""
        with self._lock:
            self._serving_mock = bool(value)
            self._recompute_locked()

    # ── state ──────────────────────────────────────────────────────────────
    def _open_critical(self) -> list[str]:
        return [
            name for name, c in self._circuits.items()
            if name in CRITICAL_SOURCES and c.is_open(self.threshold)
        ]

    def _recompute_locked(self) -> None:
        """Recompute degraded flag; fire ONE alert on each transition."""
        open_critical = self._open_critical()
        now_degraded = bool(open_critical) or self._serving_mock
        if now_degraded == self._degraded:
            return  # no transition — stay quiet, never spam
        self._degraded = now_degraded
        if self.alert_sink:
            try:
                if now_degraded:
                    reason = []
                    if open_critical:
                        reason.append("sources down: " + ", ".join(sorted(open_critical)))
                    if self._serving_mock:
                        reason.append("serving MOCK data")
                    self.alert_sink(
                        "⚠️ MAP TRADE data layer DEGRADED — " + "; ".join(reason)
                        + ". Live prices are NOT reliable; treat signals with caution."
                    )
                else:
                    self.alert_sink("✅ MAP TRADE data layer RECOVERED — live sources healthy again.")
            except Exception:
                # Alerting must never crash the data path.
                pass

    @property
    def degraded(self) -> bool:
        return self._degraded

    @property
    def serving_mock(self) -> bool:
        return self._serving_mock

    def snapshot(self) -> dict:
        """Machine-readable health for the SSE payload / dashboards."""
        with self._lock:
            open_critical = self._open_critical()
            return {
                "degraded":      self._degraded,
                "serving_mock":  self._serving_mock,
                # "live" only when nothing critical is open and no mock in play.
                "status":        "degraded" if self._degraded else "healthy",
                "open_sources":  sorted(open_critical),
                "sources": {
                    name: {
                        "open":                 c.is_open(self.threshold),
                        "consecutive_failures": c.consecutive_failures,
                        "total_failures":       c.total_failures,
                        "total_successes":      c.total_successes,
                        "last_ok_ts":           c.last_ok_ts,
                        "last_fail_ts":         c.last_fail_ts,
                        "last_error":           c.last_error,
                    }
                    for name, c in self._circuits.items()
                },
            }

    def reset(self) -> None:
        with self._lock:
            self._circuits.clear()
            self._degraded = False
            self._serving_mock = False


# ── process-wide singleton ─────────────────────────────────────────────────
# The real alert sink (Telegram) is wired in at app startup via set_alert_sink()
# so this module stays import-safe and dependency-free for tests.
health = DataHealth()


def set_alert_sink(sink: Optional[Callable[[str], None]]) -> None:
    health.alert_sink = sink


def record_success(source: str) -> None:
    health.record_success(source)


def record_failure(source: str, error: str = "") -> None:
    health.record_failure(source, error)


def set_serving_mock(value: bool) -> None:
    health.set_serving_mock(value)


def snapshot() -> dict:
    return health.snapshot()
