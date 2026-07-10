"""Tests for data/store.py — in-memory live trading state."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.store import LiveStore


class TestLiveStore:
    def setup_method(self):
        self.store = LiveStore()

    def test_initial_prices_zero(self):
        for inst in ("NIFTY", "BANKNIFTY", "SENSEX"):
            assert self.store.prices[inst].ltp == 0.0

    def test_update_price(self):
        self.store.set_prev_close("NIFTY", 24000.0)
        self.store.update_price("NIFTY", 24100.0)
        info = self.store.prices["NIFTY"]
        assert info.ltp == 24100.0
        assert info.chg == 100.0
        assert abs(info.chg_pct - 0.42) < 0.01

    def test_update_price_no_prev_close(self):
        self.store.update_price("NIFTY", 24100.0)
        assert self.store.prices["NIFTY"].chg == 0.0

    def test_add_position_and_remove(self):
        pos = {"instrument": "NIFTY", "strike": 24000, "type": "CE", "entry": 100.0, "quantity": 65}
        self.store.add_position(pos)
        assert len(self.store.positions) == 1
        self.store.remove_position("NIFTY", 24000, "CE")
        assert len(self.store.positions) == 0

    def test_unrealized_pnl(self):
        self.store.add_position({"instrument": "NIFTY", "strike": 24000, "type": "CE",
                                  "entry": 100.0, "quantity": 65, "pnl": 500.0})
        assert self.store.unrealized_pnl == 500.0

    def test_capital_locked(self):
        self.store.add_position({"instrument": "NIFTY", "strike": 24000, "type": "CE",
                                  "entry": 100.0, "quantity": 65, "pnl": 0.0})
        assert self.store.capital_locked == 100.0 * 65

    def test_capital_available_decreases_with_open_positions(self):
        initial = self.store.capital_available
        self.store.add_position({"instrument": "NIFTY", "strike": 24000, "type": "CE",
                                  "entry": 100.0, "quantity": 65, "pnl": 0.0})
        assert self.store.capital_available < initial

    def test_add_signal_capped_at_50(self):
        for i in range(60):
            self.store.add_signal({"id": i})
        assert len(self.store.signals) == 50

    def test_signals_in_reverse_order(self):
        self.store.add_signal({"id": 1})
        self.store.add_signal({"id": 2})
        assert self.store.signals[0]["id"] == 2  # most recent first

    def test_reset_daily_clears_state(self):
        self.store.add_position({"instrument": "NIFTY", "strike": 24000, "type": "CE", "pnl": 0})
        self.store.add_signal({"id": 1})
        self.store.realized_pnl = 1000.0
        self.store.cumulative_pnl = 5000.0
        self.store.reset_daily()
        assert len(self.store.positions) == 0
        assert len(self.store.signals) == 0
        assert self.store.realized_pnl == 0.0
        assert self.store.cumulative_pnl == 5000.0  # cumulative is preserved

    def test_sse_payload_structure(self):
        payload = self.store.sse_payload()
        for key in ("ts", "prices", "candles", "indicators", "positions",
                    "signals", "pnl", "capital", "ai_status", "feed_status"):
            assert key in payload

    def test_get_daily_summary_has_keys(self):
        summary = self.store.get_daily_summary()
        for key in ("realized", "unrealized", "total", "positions",
                    "capital_available", "capital_locked"):
            assert key in summary
