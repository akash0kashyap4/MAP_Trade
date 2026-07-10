"""Tests for ai/agent.py helper functions — JSON extraction and candle table."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.agent import _extract_json, _candles_table, _build_decision_user_msg


class TestExtractJson:
    def test_plain_json(self):
        result = _extract_json('{"action": "BUY_CE", "confidence": 75}')
        assert result["action"] == "BUY_CE"

    def test_json_in_markdown_fence(self):
        text = '```json\n{"action": "NO_TRADE", "confidence": 0}\n```'
        result = _extract_json(text)
        assert result["action"] == "NO_TRADE"

    def test_json_with_surrounding_text(self):
        text = 'Here is my decision:\n{"action": "BUY_PE"}\nEnd.'
        result = _extract_json(text)
        assert result["action"] == "BUY_PE"

    def test_nested_json(self):
        text = '{"action": "BUY_CE", "indicators": {"rsi": 35}}'
        result = _extract_json(text)
        assert result["indicators"]["rsi"] == 35


class TestCandlesTable:
    def _make_candle(self, hhmm: str, close: float = 100.0) -> list:
        ts = f"2025-07-03T{hhmm}:00+05:30"
        return [ts, close - 1, close + 2, close - 3, close, 1000, 0]

    def test_returns_string(self):
        candles = [self._make_candle("09:15"), self._make_candle("09:16")]
        result = _candles_table(candles)
        assert isinstance(result, str)

    def test_shows_last_10_only(self):
        candles = [self._make_candle(f"09:{15+i:02d}") for i in range(20)]
        result = _candles_table(candles)
        assert "09:24" not in result  # only last 10
        assert "09:25" in result

    def test_header_row_present(self):
        candles = [self._make_candle("09:15")]
        result = _candles_table(candles)
        assert "close" in result.lower()


class TestBuildDecisionUserMsg:
    def _minimal_context(self) -> dict:
        return {
            "instrument": "NIFTY",
            "spot_price": 24000.0,
            "time_of_day": "10:30",
            "date": "2025-07-03",
        }

    def test_returns_string(self):
        ctx = self._minimal_context()
        result = _build_decision_user_msg(ctx, "No prior context.")
        assert isinstance(result, str)

    def test_contains_context_block(self):
        ctx = self._minimal_context()
        result = _build_decision_user_msg(ctx, "BUY_CE at 09:30")
        assert "BUY_CE at 09:30" in result

    def test_contains_instrument(self):
        ctx = self._minimal_context()
        result = _build_decision_user_msg(ctx, "")
        assert "NIFTY" in result
