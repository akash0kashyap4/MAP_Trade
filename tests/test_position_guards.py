"""Regression tests for the position-level entry guards added to the market
loop, and for the recovered-position key contract."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.trader import LiveTrader
from ai.agent import TradingAgent
from data.store import store
from config import TRADING


def _agent_buy_ce():
    agent = MagicMock(spec=TradingAgent)
    agent.decide_trade = AsyncMock(return_value={
        "action": "BUY_CE", "confidence": 8, "reasoning": "bullish",
    })
    return agent


async def _run_instrument(trader):
    dummy = [["2026-07-10T12:00:00", 24000, 24050, 23980, 24010, 1000]]
    with patch("bot.trader.get_index_candles", return_value=dummy), \
         patch("bot.trader.get_live_option_from_chain") as mock_opt, \
         patch("bot.trader.db.insert_signal", new=AsyncMock(return_value=1)), \
         patch("groww.auth.get_groww_client"), \
         patch("bot.trader.build_market_context", return_value={
             "indicators": {"rsi": 65},
             "price_structure": {"trend_bias": "BULLISH", "trend_strength": "STRONG", "phase": "EXPANSION"},
         }), \
         patch("bot.trader.get_option_chain_analytics", return_value={"pcr": 1.1}):
        store.today_candles["NIFTY"] = dummy
        await trader._process_instrument("NIFTY", "12:00")
        return mock_opt


@pytest.mark.asyncio
async def test_max_positions_blocks_entry(monkeypatch):
    store.bot_paused = False
    store.new_entries_enabled = True
    # Fill positions up to the configured max so a new entry must be blocked.
    store.positions = [
        {"instrument": "BANKNIFTY", "strike": 50000, "type": "CE", "entry": 100, "quantity": 15},
        {"instrument": "SENSEX", "strike": 80000, "type": "PE", "entry": 100, "quantity": 10},
    ]
    monkeypatch.setitem(TRADING, "max_positions", 2)

    trader = LiveTrader(_agent_buy_ce())
    trader._market_open = True
    mock_opt = await _run_instrument(trader)
    # Guard fired before we ever fetched an option → no entry attempt.
    mock_opt.assert_not_called()
    store.positions = []


@pytest.mark.asyncio
async def test_duplicate_position_blocks_entry(monkeypatch):
    store.bot_paused = False
    store.new_entries_enabled = True
    monkeypatch.setitem(TRADING, "max_positions", 5)
    store.positions = [
        {"instrument": "NIFTY", "strike": 24000, "type": "CE", "entry": 100, "quantity": 75},
    ]
    trader = LiveTrader(_agent_buy_ce())
    trader._market_open = True
    mock_opt = await _run_instrument(trader)
    mock_opt.assert_not_called()  # same instrument+CE already held
    store.positions = []


@pytest.mark.asyncio
async def test_correlated_entry_blocks_entry(monkeypatch):
    from datetime import datetime
    import pytz
    store.bot_paused = False
    store.new_entries_enabled = True
    store.positions = []
    monkeypatch.setitem(TRADING, "max_positions", 5)

    trader = LiveTrader(_agent_buy_ce())
    trader._market_open = True
    # A CE entry in another index 1 minute ago → correlated, should block.
    trader._recent_entries = [{
        "instrument": "BANKNIFTY", "direction": "CE",
        "time": datetime.now(pytz.timezone("Asia/Kolkata")),
    }]
    mock_opt = await _run_instrument(trader)
    mock_opt.assert_not_called()
    store.positions = []


@pytest.mark.asyncio
async def test_recovered_position_uses_entry_key():
    """Recovered positions must expose 'entry' (not just 'entry_price') so the
    SL monitor / exit path don't crash on a KeyError."""
    store.positions = []
    trader = LiveTrader(MagicMock(spec=TradingAgent))
    with patch("data.database.get_open_trades", new=AsyncMock(return_value=[{
             "id": 7, "trade_type": "paper", "instrument": "NIFTY", "action": "BUY_CE",
             "strike": 24000, "expiry": "2026-07-16", "entry_time": "2026-07-10T11:00:00",
             "entry_price": 120.0, "quantity": 75, "signal_id": None,
         }])), \
         patch("data.database.get_signal", new=AsyncMock(return_value=None)), \
         patch("bot.trader.get_live_option_from_chain", return_value=None), \
         patch("bot.trader.request_option_subscribe"):
        await trader.recover_active_positions()

    assert len(store.positions) == 1
    pos = store.positions[0]
    assert pos["entry"] == 120.0                     # the key the loops read
    assert pos["sl"] < 120.0 and pos["target"] > 120.0  # fallbacks filled, not None
    assert isinstance(pos["pnl"], (int, float))
    store.positions = []
