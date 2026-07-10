import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from data.store import store
from data import database as db
from bot.trader import LiveTrader
from ai.agent import TradingAgent

@pytest.mark.asyncio
async def test_trader_paused_override():
    """Verify that the trader loop tick is completely skipped if bot_paused is True."""
    agent = MagicMock(spec=TradingAgent)
    trader = LiveTrader(agent)
    
    store.bot_paused = True
    store.ai_status = "waiting"
    
    # Run the loop tick - should return immediately due to pause check
    await trader.market_loop_tick()
    
    assert store.ai_status == "paused"
    agent.decide_trade.assert_not_called()


@pytest.mark.asyncio
async def test_trader_disable_new_entries():
    """Verify that buy entry is skipped when disable_new_entries is True, but indicators/signals are still analyzed."""
    agent = MagicMock(spec=TradingAgent)
    # Mock agent decision to BUY_CE
    agent.decide_trade = AsyncMock(return_value={
        "action": "BUY_CE",
        "confidence": 8,
        "reasoning": "Strong bullish candles"
    })
    
    trader = LiveTrader(agent)
    trader._market_open = True
    trader._expiries_cache["NSE_INDEX|Nifty 50_expiry"] = "2026-07-16"
    
    # Enable disable_new_entries override
    store.disable_new_entries = True
    store.bot_paused = False
    
    # Mock market context building and dependencies
    with patch("bot.trader.get_live_option_from_chain") as mock_get_option, \
         patch("bot.trader.db.insert_signal") as mock_insert_signal, \
         patch("groww.auth.get_groww_client") as mock_gc, \
         patch.object(trader, "_check_market_open", return_value=True), \
         patch("bot.trader.build_market_context", return_value={
             "indicators": {"rsi": 65},
             "price_structure": {"trend_bias": "BULLISH", "trend_strength": "STRONG", "phase": "EXPANSION"},
         }), \
         patch("bot.trader.get_option_chain_analytics", return_value={"pcr": 1.1, "max_pain": 24200, "atm_iv": 14.5}):
        
        # We need a dummy candle list to avoid empty candle skips
        store.today_candles["NIFTY"] = [["2026-07-10T12:00:00", 24000, 24050, 23980, 24010, 1000]]
        
        await trader._process_instrument("NIFTY", "12:00")
        
        # Agent should have been consulted for the analysis/decision
        agent.decide_trade.assert_called_once()
        # insert_signal should be called
        mock_insert_signal.assert_called_once()
        # But get_live_option_from_chain should NOT be called (buy entry skipped!)
        mock_get_option.assert_not_called()


@pytest.mark.asyncio
async def test_active_positions_recovery():
    """Verify that trader's recover_active_positions correctly reconstructs store positions and subscribes to feeds."""
    agent = MagicMock(spec=TradingAgent)
    trader = LiveTrader(agent)
    
    # Reset store positions
    store.positions = []
    
    # Use context managers to patch dependencies explicitly on the source module
    with patch("data.database.get_open_trades") as mock_get_open, \
         patch("data.database.get_signal") as mock_get_signal, \
         patch("bot.trader.get_live_option_from_chain") as mock_get_option, \
         patch("bot.trader.request_option_subscribe") as mock_sub:
         
        # Mock database active open trades
        mock_get_open.return_value = [
            {
                "id": 42,
                "trade_type": "paper",
                "instrument": "NIFTY",
                "action": "BUY_CE",
                "strike": 24000,
                "expiry": "2026-07-16",
                "entry_time": "2026-07-10T11:00:00",
                "entry_price": 120.0,
                "quantity": 65,
                "signal_id": 101,
            }
        ]
        
        # Mock corresponding signal
        mock_get_signal.return_value = {
            "id": 101,
            "ai_response": '{"action": "BUY_CE", "confidence": 8, "sl_premium": 95.0, "target_premium": 180.0}'
        }
        
        # Mock option chain retrieval
        mock_get_option.return_value = {
            "ltp": 122.0,
            "strike": 24000,
            "expiry": "2026-07-16",
            "instrument_key": "NSE-NIFTY-2026-07-16-24000-CE"
        }
        
        await trader.recover_active_positions()
        
        # Assertions to verify the mocks were actually used
        mock_get_open.assert_called_once()
        mock_get_signal.assert_called_once_with(101)
        
        # Verify store contains the recovered position
        assert len(store.positions) == 1
        pos = store.positions[0]
        assert pos["instrument"] == "NIFTY"
        assert pos["strike"] == 24000
        assert pos["sl"] == 95.0
        assert pos["target"] == 180.0
        assert pos["trade_db_id"] == 42
        
        # Verify subscription request was dispatched
        mock_sub.assert_called_once_with("NSE-NIFTY-2026-07-16-24000-CE")
