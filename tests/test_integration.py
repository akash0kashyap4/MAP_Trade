import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from data.store import store
from bot.trader import LiveTrader
from ai.agent import TradingAgent


@pytest.mark.asyncio
async def test_trader_paused_override():
    """Verify that the trader loop tick is completely skipped if bot_paused is True."""
    agent = MagicMock(spec=TradingAgent)
    trader = LiveTrader(agent)

    store.bot_paused = True
    store.ai_status = "waiting"

    await trader.market_loop_tick()

    assert store.ai_status == "paused"
    agent.decide_trade.assert_not_called()


@pytest.mark.asyncio
async def test_trader_disable_new_entries():
    """Verify that buy entry is skipped when new_entries_enabled is False."""
    agent = MagicMock(spec=TradingAgent)
    agent.decide_trade = AsyncMock(return_value={
        "action": "BUY_CE",
        "confidence": 8,
        "reasoning": "Strong bullish candles"
    })

    trader = LiveTrader(agent)
    trader._market_open = True
    trader._expiries_cache["NSE_INDEX|Nifty 50_expiry"] = "2026-07-16"

    store.new_entries_enabled = False
    store.bot_paused = False

    dummy_candles = [["2026-07-10T12:00:00", 24000, 24050, 23980, 24010, 1000]]
    with patch("bot.trader.get_index_candles", return_value=dummy_candles), \
         patch("bot.trader.get_live_option_from_chain") as mock_get_option, \
         patch("bot.trader.db.insert_signal") as mock_insert_signal, \
         patch("groww.auth.get_groww_client"), \
         patch.object(trader, "_check_market_open", return_value=True), \
         patch("bot.trader.build_market_context", return_value={
             "indicators": {"rsi": 65},
             "price_structure": {"trend_bias": "BULLISH", "trend_strength": "STRONG", "phase": "EXPANSION"},
         }), \
         patch("bot.trader.get_option_chain_analytics", return_value={"pcr": 1.1, "max_pain": 24200, "atm_iv": 14.5}):

        store.today_candles["NIFTY"] = [["2026-07-10T12:00:00", 24000, 24050, 23980, 24010, 1000]]

        await trader._process_instrument("NIFTY", "12:00")

        agent.decide_trade.assert_called_once()
        mock_insert_signal.assert_called_once()
        mock_get_option.assert_not_called()
