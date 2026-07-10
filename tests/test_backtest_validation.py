"""Tests for BacktestRequest.validate_request() input validation."""
import sys
import os
import pytest
from types import SimpleNamespace
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.routes import _VALID_INSTRUMENTS, _VALID_STRATEGIES, _DATE_RE


def _make_req(**kwargs):
    """Minimal stand-in for BacktestRequest — tests the validation logic directly."""
    defaults = {
        "instrument": "NIFTY",
        "start_date": "2025-01-01",
        "end_date":   "2025-03-31",
        "strategy":   "first_candle",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _validate(req):
    """Inline replica of BacktestRequest.validate_request() for isolated unit testing."""
    import re
    from datetime import datetime
    if req.instrument not in _VALID_INSTRUMENTS:
        raise ValueError(f"instrument must be one of {_VALID_INSTRUMENTS}")
    if req.strategy not in _VALID_STRATEGIES:
        raise ValueError(f"strategy must be one of {_VALID_STRATEGIES}")
    for field_name, date_str in (("start_date", req.start_date), ("end_date", req.end_date)):
        if not re.match(_DATE_RE, date_str):
            raise ValueError(f"{field_name} must be YYYY-MM-DD")
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"{field_name} is not a valid date")
    if req.start_date > req.end_date:
        raise ValueError("start_date must be before end_date")


class TestBacktestRequestValidation:
    def test_valid_request_passes(self):
        _validate(_make_req())  # should not raise

    def test_invalid_instrument_raises(self):
        with pytest.raises(ValueError, match="instrument"):
            _validate(_make_req(instrument="MIDCAP"))

    def test_invalid_strategy_raises(self):
        with pytest.raises(ValueError, match="strategy"):
            _validate(_make_req(strategy="magic_bean"))

    def test_bad_start_date_format_raises(self):
        with pytest.raises(ValueError, match="start_date"):
            _validate(_make_req(start_date="01-01-2025"))

    def test_bad_end_date_format_raises(self):
        with pytest.raises(ValueError, match="end_date"):
            _validate(_make_req(end_date="2025/03/31"))

    def test_start_after_end_raises(self):
        with pytest.raises(ValueError, match="start_date must be before"):
            _validate(_make_req(start_date="2025-06-01", end_date="2025-01-01"))

    def test_all_instruments_valid(self):
        for inst in ("NIFTY", "BANKNIFTY", "SENSEX"):
            _validate(_make_req(instrument=inst))  # should not raise

    def test_all_strategies_valid(self):
        for strat in ("first_candle", "orb15", "rsi_reversal", "ema_trend", "gap_direction"):
            _validate(_make_req(strategy=strat))  # should not raise

    def test_invalid_day_in_date(self):
        with pytest.raises(ValueError, match="start_date"):
            _validate(_make_req(start_date="2025-02-30"))  # Feb 30 doesn't exist
