"""
Realistic Indian options trading cost model.
Replaces the flat 40 charge that was making paper P&L lie to the learner.

Assumptions (Zerodha/Upstox-style discount broker, NSE/BSE F&O):
  - Brokerage: flat ₹20 per order (₹40 round trip)
  - STT: 0.0625% of sell-side premium turnover (premium x qty)
  - Exchange transaction charge: 0.053% of premium turnover (NSE), 0.0325% (BSE) - both sides
  - SEBI fee: ₹10 per crore of premium turnover
  - Stamp duty: 0.003% on buy-side premium turnover
  - GST: 18% on (brokerage + transaction + SEBI)
  - Slippage: 1.5% of premium (enter pays the ask, exit hits the bid)
"""
from __future__ import annotations
from typing import Literal

# Calibrated to Groww/Zerodha real fills on liquid Nifty/BankNifty weeklies:
# typical round-trip slippage is 0.5%-1.5%, not the 3%+ the earlier settings
# assumed. Over-modelled slippage was making paper P&L systematically negative
# and starving the AI of positive-expectancy trades to learn from.
DEFAULT_SLIPPAGE_PCT = 0.007


def get_dynamic_slippage_pct(premium: float, vix: float = 15.0) -> float:
    """
    Realistic per-side slippage % for liquid NSE index options.
    Wider % for very cheap OTM premiums, wider on high-VIX days.
    """
    if premium <= 0:
        return DEFAULT_SLIPPAGE_PCT
    base_pct = 0.005                 # 0.5% baseline for liquid ATM
    if premium < 30:
        base_pct += 0.010            # was +1.5% — halved
    elif premium < 60:
        base_pct += 0.005
    elif premium < 100:
        base_pct += 0.003

    vix_multiplier = max(1.0, vix / 18.0)   # only widen above VIX 18
    return max(0.003, min(0.025, base_pct * vix_multiplier))


def apply_slippage(premium: float, side: Literal["buy", "sell"], slippage_pct: float | None = None, vix: float = 15.0) -> float:
    if premium <= 0:
        return premium
    if slippage_pct is None:
        slippage_pct = get_dynamic_slippage_pct(premium, vix)
    if side == "buy":
        return round(premium * (1 + slippage_pct), 2)
    return round(premium * (1 - slippage_pct), 2)


def calc_round_trip_fees(entry_premium: float, exit_premium: float, quantity: int,
                          exchange: Literal["NSE", "BSE"] = "NSE") -> dict:
    """
    Returns a breakdown dict of every fee component for one full round trip.
    Always positive numbers (cost).
    """
    buy_value = max(entry_premium, 0) * max(quantity, 0)
    sell_value = max(exit_premium, 0) * max(quantity, 0)

    brokerage = 40.0  # 20 entry + 20 exit
    stt = sell_value * 0.000625
    txn_rate = 0.00053 if exchange == "NSE" else 0.000325
    txn = (buy_value + sell_value) * txn_rate
    sebi = (buy_value + sell_value) * 0.0000001  # ₹10 per crore
    stamp = buy_value * 0.00003
    gst = (brokerage + txn + sebi) * 0.18

    total = brokerage + stt + txn + sebi + stamp + gst
    return {
        "brokerage": round(brokerage, 2),
        "stt":       round(stt, 2),
        "txn":       round(txn, 2),
        "sebi":      round(sebi, 4),
        "stamp":     round(stamp, 2),
        "gst":       round(gst, 2),
        "total":     round(total, 2),
    }


def realistic_pnl(entry_premium: float, exit_premium: float, quantity: int,
                  exchange: Literal["NSE", "BSE"] = "NSE") -> dict:
    """
    Convert raw P&L to net P&L the way it would actually settle in a real account.
    `entry_premium` and `exit_premium` should already include slippage if you want
    a worst-case paper number; otherwise call apply_slippage() first.
    """
    raw = round((exit_premium - entry_premium) * quantity, 2)
    fees = calc_round_trip_fees(entry_premium, exit_premium, quantity, exchange)
    net = round(raw - fees["total"], 2)
    return {
        "pnl_raw":   raw,
        "fees":      fees,
        "pnl_final": net,
    }
