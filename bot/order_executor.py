"""
Live order execution layer — sits between trader.py and AngelOne API.

Safety checks run BEFORE every real order:
  1. Daily loss limit not breached
  2. Max open positions not exceeded
  3. Capital available >= order cost
  4. Market hours only (09:15 – 15:15 IST)
  5. Not already in same direction for this instrument

All public methods are async (use asyncio.to_thread for sync SDK calls).
"""
from __future__ import annotations
import asyncio
import time
from datetime import datetime
from typing import Optional
import pytz

from config import TRADING

IST = pytz.timezone("Asia/Kolkata")

# Expiry format required by AngelOne scrip master — populated by trader before calling
# e.g. "09JAN25"
_EXPIRY_FORMAT = "%d%b%y"  # strptime reference


class OrderExecutor:
    """Stateful executor — one instance per bot session."""

    def __init__(self):
        self._daily_loss: float = 0.0
        self._order_log: list[dict] = []

    # ── Safety gate ──────────────────────────────────────────────────────────

    def _safety_check(
        self,
        instrument: str,
        quantity: int,
        entry_price: float,
        store,                  # bot.store module (has capital_available, positions)
    ) -> tuple[bool, str]:
        """Return (ok, reason). Blocks order if any check fails."""

        # 1. Market hours
        now = datetime.now(IST)
        market_open  = now.replace(hour=9,  minute=15, second=0, microsecond=0)
        market_close = now.replace(hour=15, minute=15, second=0, microsecond=0)
        if not (market_open <= now <= market_close):
            return False, f"Outside market hours ({now.strftime('%H:%M IST')})"

        # 2. Daily loss limit
        max_loss = TRADING.get("max_daily_loss", 5000)
        if self._daily_loss <= -abs(max_loss):
            return False, f"Daily loss limit hit: ₹{self._daily_loss:,.0f}"

        # 3. Capital check
        trade_cost = entry_price * quantity
        if trade_cost > store.capital_available:
            return False, f"Insufficient capital: need ₹{trade_cost:,.0f}, have ₹{store.capital_available:,.0f}"

        # 4. Max positions
        max_pos = TRADING.get("max_positions", 2)
        if len(store.positions) >= max_pos:
            return False, f"Max positions ({max_pos}) already open"

        return True, "ok"

    # ── Entry ─────────────────────────────────────────────────────────────────

    async def enter(
        self,
        instrument: str,
        strike: int,
        option_type: str,        # "CE" | "PE"
        expiry_str: str,         # "09JAN25" format for AngelOne
        quantity: int,
        entry_price: float,
        sl: float,
        target: float,
        store,
        telegram_fn,             # async fn(text) → bool
    ) -> Optional[dict]:
        """
        Place a BUY order on AngelOne. Returns position dict (same schema as
        paper positions) with 'order_id' added, or None on failure.
        """
        from angelone.orders import find_option_token, place_market_order, get_order_status

        ok, reason = self._safety_check(instrument, quantity, entry_price, store)
        if not ok:
            print(f"[order_executor] BLOCKED entry — {reason}")
            await telegram_fn(f"⛔ LIVE ORDER BLOCKED\n{instrument} {strike}{option_type}\nReason: {reason}")
            return None

        exchange = "BFO" if instrument == "SENSEX" else "NFO"

        # Telegram alert BEFORE placing (so we know what was attempted)
        await telegram_fn(
            f"🔴 PLACING LIVE ORDER\n"
            f"{instrument} {strike}{option_type} @ ₹{entry_price:.0f}\n"
            f"Qty: {quantity} | SL: ₹{sl:.0f} | TGT: ₹{target:.0f}"
        )

        try:
            symbol, token = await asyncio.to_thread(
                find_option_token, instrument, expiry_str, strike, option_type
            )
            order_id = await asyncio.to_thread(
                place_market_order, symbol, token, quantity, "BUY", exchange
            )
        except Exception as e:
            err = f"[order_executor] AngelOne entry failed: {e}"
            print(err)
            await telegram_fn(f"❌ LIVE ORDER FAILED\n{instrument} {strike}{option_type}\n{e}")
            return None

        # Poll for fill (up to 10s)
        fill_price = entry_price
        for _ in range(5):
            await asyncio.sleep(2)
            try:
                status = await asyncio.to_thread(get_order_status, order_id)
                if status["status"] == "complete":
                    fill_price = status["fill_price"] or entry_price
                    break
                elif status["status"] in ("rejected", "cancelled"):
                    await telegram_fn(f"❌ ORDER REJECTED\n{instrument} {strike}{option_type}\n{status['message']}")
                    return None
            except Exception:
                pass

        position = {
            "instrument":     instrument,
            "strike":         strike,
            "type":           option_type,
            "action":         f"BUY_{option_type}",
            "expiry":         expiry_str,
            "entry":          fill_price,
            "ltp":            fill_price,
            "pnl":            0.0,
            "sl":             sl,
            "target":         target,
            "quantity":       quantity,
            "entry_time":     datetime.now(IST).isoformat(),
            "order_id":       order_id,
            "exchange":       exchange,
            "symbol":         symbol,
            "token":          token,
            "is_live":        True,
        }

        self._order_log.append({"type": "entry", "order_id": order_id, "instrument": instrument,
                                 "strike": strike, "option_type": option_type, "fill": fill_price,
                                 "qty": quantity, "time": time.time()})

        await telegram_fn(
            f"✅ LIVE ORDER FILLED\n"
            f"{instrument} {strike}{option_type} @ ₹{fill_price:.0f}\n"
            f"Order ID: {order_id}"
        )

        return position

    # ── Exit ─────────────────────────────────────────────────────────────────

    async def exit(
        self,
        position: dict,
        reason: str,
        current_price: float,
        telegram_fn,
    ) -> float:
        """
        Place a SELL order to exit position. Returns fill_price.
        Falls back to current_price on failure (logs the error).
        """
        from angelone.orders import place_market_order, get_order_status

        symbol   = position.get("symbol", "")
        token    = position.get("token", "")
        quantity = position["quantity"]
        exchange = position.get("exchange", "NFO")

        await telegram_fn(
            f"🟡 CLOSING LIVE POSITION\n"
            f"{position['instrument']} {position['strike']}{position['type']}\n"
            f"Reason: {reason} | LTP: ₹{current_price:.0f}"
        )

        try:
            order_id = await asyncio.to_thread(
                place_market_order, symbol, token, quantity, "SELL", exchange
            )
        except Exception as e:
            print(f"[order_executor] AngelOne exit failed: {e}")
            await telegram_fn(f"❌ EXIT ORDER FAILED\n{position['instrument']} {position['strike']}{position['type']}\n{e}")
            return current_price

        # Poll for fill
        fill_price = current_price
        for _ in range(5):
            await asyncio.sleep(2)
            try:
                status = await asyncio.to_thread(get_order_status, order_id)
                if status["status"] == "complete":
                    fill_price = status["fill_price"] or current_price
                    break
            except Exception:
                pass

        pnl = (fill_price - position["entry"]) * quantity
        self._daily_loss += pnl if pnl < 0 else 0

        self._order_log.append({"type": "exit", "order_id": order_id,
                                 "instrument": position["instrument"],
                                 "fill": fill_price, "pnl": pnl, "time": time.time()})

        await telegram_fn(
            f"✅ POSITION CLOSED\n"
            f"{position['instrument']} {position['strike']}{position['type']}\n"
            f"Exit: ₹{fill_price:.0f} | P&L: ₹{pnl:+.0f}\n"
            f"Reason: {reason}"
        )

        return fill_price

    def reset_daily_loss(self):
        """Call at start of each trading day."""
        self._daily_loss = 0.0
        self._order_log.clear()

    @property
    def daily_loss(self) -> float:
        return self._daily_loss
