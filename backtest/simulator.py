from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


BROKERAGE_PER_SIDE = 20.0
STT_RATE = 0.0005


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
    slippage = entry_price * 0.005
    actual_entry = entry_price + slippage

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
            pnl_raw     = (exit_price - actual_entry) * quantity
            pnl_final   = pnl_raw - _brokerage(actual_entry, exit_price, quantity)
            return TradeResult(actual_entry, exit_price, exit_reason, quantity, pnl_raw, pnl_final, 0, idx)

        if h >= target_price:
            exit_price  = target_price
            exit_reason = "TARGET"
            pnl_raw     = (exit_price - actual_entry) * quantity
            pnl_final   = pnl_raw - _brokerage(actual_entry, exit_price, quantity)
            return TradeResult(actual_entry, exit_price, exit_reason, quantity, pnl_raw, pnl_final, 0, idx)

    last = candles_after_entry[-1]
    exit_price  = float(last[4])
    exit_reason = "EOD"
    pnl_raw     = round((exit_price - actual_entry) * quantity, 2)
    pnl_final   = round(pnl_raw - _brokerage(actual_entry, exit_price, quantity), 2)
    return TradeResult(actual_entry, exit_price, exit_reason, quantity, pnl_raw, pnl_final, 0, len(candles_after_entry) - 1)


def _brokerage(entry: float, exit_p: float, qty: int) -> float:
    buy_side  = BROKERAGE_PER_SIDE
    sell_side = BROKERAGE_PER_SIDE + (exit_p * qty * STT_RATE)
    return buy_side + sell_side
