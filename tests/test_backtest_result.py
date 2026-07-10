"""Tests for backtest/engine.py BacktestResult dataclass and helpers."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.engine import BacktestResult, _time_str, _mins


class TestTimeStr:
    def test_iso_timestamp(self):
        candle = ["2025-07-03T09:15:00+05:30", 100, 105, 98, 102, 1000, 0]
        assert _time_str(candle) == "09:15"

    def test_short_timestamp(self):
        candle = ["09:15", 100, 105, 98, 102, 1000, 0]
        assert _time_str(candle) == "09:15"


class TestMins:
    def test_market_open(self):
        assert _mins("09:15") == 9 * 60 + 15

    def test_noon(self):
        assert _mins("12:00") == 12 * 60

    def test_market_close(self):
        assert _mins("15:30") == 15 * 60 + 30


class TestBacktestResult:
    def test_default_values(self):
        r = BacktestResult(instrument="NIFTY", start_date="2025-01-01", end_date="2025-01-31")
        assert r.total_trades == 0
        assert r.wins == 0
        assert r.losses == 0
        assert r.win_rate == 0.0
        assert r.total_pnl == 0.0

    def test_trades_list_independent(self):
        r1 = BacktestResult(instrument="NIFTY", start_date="2025-01-01", end_date="2025-01-31")
        r2 = BacktestResult(instrument="BANKNIFTY", start_date="2025-01-01", end_date="2025-01-31")
        r1.trades.append({"pnl": 100})
        assert len(r2.trades) == 0  # dataclass field default_factory isolation
