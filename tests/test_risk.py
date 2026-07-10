import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta
import pytz

from bot.risk import (
    calc_quantity,
    calc_sl_price,
    calc_target_price,
    calc_trailing_sl,
    max_positions_reached,
    check_risk_limits,
    classify_signal_quality,
)
from data.store import store
from config import TRADING

IST = pytz.timezone("Asia/Kolkata")


def test_basic_calcs():
    assert calc_quantity("NIFTY", lots=1) == 65
    assert calc_quantity("BANKNIFTY", lots=2) == 60
    assert calc_sl_price(100.0, 500, 50) == 90.0
    assert calc_target_price(100.0, 1000, 50) == 120.0
    
    # trailing SL
    # entry=100, current=110, current_sl=80, qty=50 (target_rs=1000 => tgt_pts=20)
    # trigger = 20 * 0.40 = 8 pts profit (profit is 10, so trigger is met!)
    # step_pts = 20 * 0.20 = 4 pts. new_sl = 110 - 4 = 106.0
    assert calc_trailing_sl(100.0, 110.0, 80.0, 50) == 106.0


def test_max_positions():
    assert max_positions_reached([]) is False
    assert max_positions_reached([1, 2]) is True


@pytest.mark.asyncio
@patch("data.database.get_today_trades", new_callable=AsyncMock)
async def test_check_risk_limits(mock_get_today):
    # Setup test configuration values
    TRADING["session_profit_lock"] = 5000
    TRADING["max_trades_per_symbol"] = 3
    TRADING["consecutive_loss_limit"] = 2
    TRADING["max_risk_per_trade"] = 1000
    
    # 1. Test Profit Lock
    store.realized_pnl = 6000
    allowed, reason, qty = await check_risk_limits("NIFTY", "BUY_CE", 100.0, 80.0, 65)
    assert allowed is False
    assert "profit lock" in reason.lower()
    
    # Reset realized_pnl
    store.realized_pnl = 0.0
    
    # 2. Test Max Trades Per Symbol
    # Mock database to return 3 trades for NIFTY today
    mock_get_today.return_value = [
        {"instrument": "NIFTY", "entry_time": "2026-07-10T10:00:00"},
        {"instrument": "NIFTY", "entry_time": "2026-07-10T11:00:00"},
        {"instrument": "NIFTY", "entry_time": "2026-07-10T12:00:00"},
    ]
    allowed, reason, qty = await check_risk_limits("NIFTY", "BUY_CE", 100.0, 80.0, 65)
    assert allowed is False
    assert "max trades" in reason.lower()
    
    # 3. Test Cooldown
    # Reset mock to return trades with exits (losses)
    now_str = datetime.now(IST).isoformat()
    mock_get_today.return_value = [
        {"instrument": "BANKNIFTY", "entry_time": "2026-07-10T10:00:00", "exit_time": now_str, "pnl_final": -100},
        {"instrument": "BANKNIFTY", "entry_time": "2026-07-10T11:00:00", "exit_time": now_str, "pnl_final": -200},
    ]
    allowed, reason, qty = await check_risk_limits("BANKNIFTY", "BUY_CE", 100.0, 80.0, 30)
    assert allowed is False
    assert "cooldown active" in reason.lower()
    
    # 4. Test Risk Resizing
    mock_get_today.return_value = []
    # entry=100, sl=70, qty=65. Risk = (100-70)*65 = 1950 > 1000
    # allowed max risk is 1000 => max qty = 1000/30 = 33.3 => 0 lots?
    allowed, reason, qty = await check_risk_limits("NIFTY", "BUY_CE", 100.0, 70.0, 65)
    # Wait, 1 lot is 65. If 1 lot risk = 65 * 30 = 1950, which is > 1000. So even 1 lot exceeds!
    assert allowed is False
    assert "exceeds max risk cap" in reason
    
    # Now check where downsizing is possible
    # Max risk is 1000. Let's make entry=100, sl=90 (risk=10 per unit). qty=130 (2 lots) => Risk = 1300 > 1000
    # 1 lot is 65 => Risk = 650 <= 1000. So it should downsize to 65!
    allowed, reason, qty = await check_risk_limits("NIFTY", "BUY_CE", 100.0, 90.0, 130)
    assert allowed is True
    assert qty == 65
    assert "resized" in reason.lower()


def test_classify_signal():
    premarket = {"bias": "BULLISH", "reasoning": "SGX green"}
    
    # Strong buy (confidence=9, aligned with bias)
    decision = {"action": "BUY_CE", "confidence": 9, "reasoning": "Breakout"}
    res = classify_signal_quality(decision, premarket, vix=15.0)
    assert res["label"] == "STRONG"
    assert res["score"] >= 75
    
    # Weak buy (confidence=6, opposing bias)
    decision = {"action": "BUY_PE", "confidence": 6, "reasoning": "Slight drop"}
    res = classify_signal_quality(decision, premarket, vix=15.0)
    assert res["label"] == "AVOID"  # 60 - 20 = 40 < 50
