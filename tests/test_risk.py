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
    
    # entry=100, current=110, current_sl=80, qty=50 (target_rs=1000 => tgt_pts=20)
    # trigger = 20 * 0.40 = 8 pts profit (profit is 10, so trigger is met!)
    # step_pts = 20 * 0.20 = 4 pts. new_sl = 110 - 4 = 106.0
    assert calc_trailing_sl(100.0, 110.0, 80.0, 50) == 106.0


def test_max_positions():
    # Read the configured cap rather than hardcoding it — the limit was raised
    # from 2 to 3 to let the bot hold more concurrent setups, and the test must
    # track the config, not a stale literal.
    cap = TRADING["max_positions"]
    assert max_positions_reached([]) is False
    assert max_positions_reached(list(range(cap - 1))) is False
    assert max_positions_reached(list(range(cap))) is True


@pytest.mark.asyncio
@patch("data.database.get_today_trades", new_callable=AsyncMock)
async def test_check_risk_limits(mock_get_today):
    TRADING["session_profit_lock"] = 5000
    TRADING["max_trades_per_symbol"] = 3
    TRADING["consecutive_loss_limit"] = 2
    TRADING["max_risk_per_trade"] = 1000
    
    # 1. Profit lock no longer BLOCKS new entries. By design the session
    # profit-lock now only pins open positions' SL to breakeven (handled in the
    # trader loop), so the bot keeps hunting fresh setups after a good morning
    # instead of going dead for the rest of the day. Use inputs that trip NO
    # other limit (empty trade history, tight risk within the cap) so this
    # isolates profit-lock behaviour: entries above the lock must be allowed.
    mock_get_today.return_value = []
    store.realized_pnl = 6000
    allowed, reason, qty = await check_risk_limits("NIFTY", "BUY_CE", 100.0, 95.0, 65)
    assert allowed is True
    assert "profit lock" not in reason.lower()

    store.realized_pnl = 0.0
    
    # 2. Test Max Trades Per Symbol
    mock_get_today.return_value = [
        {"instrument": "NIFTY", "entry_time": "2026-07-10T10:00:00"},
        {"instrument": "NIFTY", "entry_time": "2026-07-10T11:00:00"},
        {"instrument": "NIFTY", "entry_time": "2026-07-10T12:00:00"},
    ]
    allowed, reason, qty = await check_risk_limits("NIFTY", "BUY_CE", 100.0, 80.0, 65)
    assert allowed is False
    assert "max trades" in reason.lower()
    
    # 3. Test Cooldown
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
    allowed, reason, qty = await check_risk_limits("NIFTY", "BUY_CE", 100.0, 70.0, 65)
    assert allowed is False
    assert "exceeds max risk cap" in reason
    
    allowed, reason, qty = await check_risk_limits("NIFTY", "BUY_CE", 100.0, 90.0, 130)
    assert allowed is True
    assert qty == 65
    assert "resized" in reason.lower()


def test_classify_signal():
    premarket = {"bias": "BULLISH", "reasoning": "SGX green"}
    
    decision = {"action": "BUY_CE", "confidence": 9, "reasoning": "Breakout"}
    res = classify_signal_quality(decision, premarket, vix=15.0)
    assert res["label"] == "STRONG"
    assert res["score"] >= 75
    
    decision = {"action": "BUY_PE", "confidence": 6, "reasoning": "Slight drop"}
    res = classify_signal_quality(decision, premarket, vix=15.0)
    assert res["label"] == "AVOID"  # 60 - 20 = 40 < 50
