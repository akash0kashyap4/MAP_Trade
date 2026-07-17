from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from bot.fees import apply_slippage, realistic_pnl


@dataclass
class TradeResult:
    entry_price: float
    exit_price: float
    exit_reason: str
    quantity: int
    pnl_raw: float
    pnl_final: float
    entry_candle_idx: int
    exit_candle_idx: int


def simulate_trade(
    entry_price: float,
    candles_after_entry: list,
    sl_rs: float,
    target_rs: float,
    lot_size: int,
    lots: int,
    trailing_sl_trigger: float = 0.5,
    trailing_sl_step: float = 0.25,
) -> Optional[TradeResult]:
    if not candles_after_entry or entry_price <= 0:
        return None

    quantity = lot_size * lots
    
    # Apply entry slippage dynamically (using default VIX 15.0 for backtest consistency)
    actual_entry = apply_slippage(entry_price, "buy", vix=15.0)

    sl_pts    = sl_rs    / quantity
    tgt_pts   = target_rs / quantity

    sl_price     = actual_entry - sl_pts
    target_price = actual_entry + tgt_pts

    trailing_active = False
    highest_price   = actual_entry
    current_sl      = sl_price
    trailing_trigger_pts = tgt_pts * trailing_sl_trigger

    for idx, candle in enumerate(candles_after_entry):
        _, _, h, candle_low, _ = candle[0], candle[1], candle[2], candle[3], candle[4]

        if h > highest_price:
            highest_price = h

        profit_so_far = highest_price - actual_entry
        if profit_so_far >= trailing_trigger_pts and not trailing_active:
            trailing_active = True

        if trailing_active:
            new_sl = highest_price - (tgt_pts * trailing_sl_step)
            if new_sl > current_sl:
                current_sl = new_sl

        if candle_low <= current_sl:
            exit_price  = current_sl
            exit_reason = "SL"
            # Apply exit slippage dynamically on SL exit
            actual_exit = apply_slippage(exit_price, "sell", vix=15.0)
            breakdown = realistic_pnl(actual_entry, actual_exit, quantity)
            return TradeResult(actual_entry, actual_exit, exit_reason, quantity, breakdown["pnl_raw"], breakdown["pnl_final"], 0, idx)

        if h >= target_price:
            exit_price  = target_price
            exit_reason = "TARGET"
            # Apply exit slippage dynamically on target exit
            actual_exit = apply_slippage(exit_price, "sell", vix=15.0)
            breakdown = realistic_pnl(actual_entry, actual_exit, quantity)
            return TradeResult(actual_entry, actual_exit, exit_reason, quantity, breakdown["pnl_raw"], breakdown["pnl_final"], 0, idx)

    last = candles_after_entry[-1]
    exit_price  = float(last[4])
    exit_reason = "EOD"
    # Apply exit slippage dynamically on EOD exit
    actual_exit = apply_slippage(exit_price, "sell", vix=15.0)
    breakdown = realistic_pnl(actual_entry, actual_exit, quantity)
    return TradeResult(actual_entry, actual_exit, exit_reason, quantity, breakdown["pnl_raw"], breakdown["pnl_final"], 0, len(candles_after_entry) - 1)
