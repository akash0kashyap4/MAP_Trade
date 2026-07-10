"""Tests for data/candle_cache.py — sync SQLite candle store."""
import sys
import os
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_candle(ts: str, close: float = 100.0) -> list:
    return [ts, close - 1, close + 1, close - 2, close, 1000, 0]


class TestCandleCache:
    """Use a temp DB so tests don't pollute the real cache."""

    def setup_method(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        import config
        self._orig_db = config.DB_PATH
        config.DB_PATH = self._tmp.name
        # Reload candle_cache with new DB_PATH
        import importlib
        import data.candle_cache as cc
        importlib.reload(cc)
        self.cc = cc

    def teardown_method(self):
        import config
        config.DB_PATH = self._orig_db
        import importlib
        import data.candle_cache as cc
        importlib.reload(cc)
        try:
            os.unlink(self._tmp.name)
        except Exception:
            pass


    def test_has_candles_empty(self):
        assert not self.cc.has_candles("NSE_NIFTY", "2025-01-02")

    def test_save_and_retrieve(self):
        candles = [_make_candle(f"2025-01-02T09:{15+i:02d}:00+05:30") for i in range(20)]
        self.cc.save_candles("NSE_NIFTY", candles)
        assert self.cc.has_candles("NSE_NIFTY", "2025-01-02")

    def test_get_candles_returns_correct_count(self):
        candles = [_make_candle(f"2025-01-02T09:{15+i:02d}:00+05:30") for i in range(20)]
        self.cc.save_candles("NSE_NIFTY", candles)
        result = self.cc.get_candles("NSE_NIFTY", "2025-01-02")
        assert len(result) == 20

    def test_duplicate_candles_not_inserted(self):
        candles = [_make_candle("2025-01-02T09:15:00+05:30")] * 5
        self.cc.save_candles("NSE_NIFTY", candles)
        result = self.cc.get_candles("NSE_NIFTY", "2025-01-02")
        assert len(result) == 1

    def test_get_candles_returns_ohlcv_format(self):
        candles = [_make_candle("2025-01-02T09:15:00+05:30", close=24000.0)]
        self.cc.save_candles("NSE_NIFTY", candles)
        result = self.cc.get_candles("NSE_NIFTY", "2025-01-02")
        assert len(result) == 1
        row = result[0]
        assert len(row) == 7  # [ts, o, h, l, c, vol, oi]
        assert float(row[4]) == 24000.0  # close

    def test_get_cache_stats_returns_list(self):
        stats = self.cc.get_cache_stats()
        assert isinstance(stats, list)
