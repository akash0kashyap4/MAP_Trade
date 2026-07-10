from datetime import datetime
import pytz
from config import TRADING, LOT_SIZES
from data.store import store
from data import database as db

IST = pytz.timezone("Asia/Kolkata")


def calc_quantity(instrument: str, lots: int = None) -> int:
    lots = lots or TRADING["lots"]
    return LOT_SIZES.get(instrument, 75) * lots


def calc_sl_price(entry: float, sl_rs: float, quantity: int) -> float:
    sl_pts = sl_rs / quantity
    return round(entry - sl_pts, 2)


def calc_target_price(entry: float, target_rs: float, quantity: int) -> float:
    tgt_pts = target_rs / quantity
    return round(entry + tgt_pts, 2)


def calc_trailing_sl(entry: float, current: float, current_sl: float, quantity: int) -> float:
    target_rs = TRADING["target_rs"]
    tgt_pts   = target_rs / quantity
    profit    = current - entry
    trigger   = tgt_pts * TRADING["trailing_sl_trigger"]

    if profit < trigger:
        return current_sl

    step_pts = tgt_pts * TRADING["trailing_sl_step"]
    new_sl   = current - step_pts
    return round(max(new_sl, current_sl), 2)


def max_positions_reached(open_positions: list) -> bool:
    return len(open_positions) >= TRADING["max_positions"]


async def check_risk_limits(instrument: str, action: str, entry_price: float, sl_price: float, quantity: int) -> tuple[bool, str, int]:
    """
    Checks all configured risk limits:
    - Session profit lock
    - Max trades per symbol per day
    - Consecutive loss cooldowns
    - Per-trade risk cap & position sizing (downsizes quantity if needed)
    
    Returns (allowed, reason, adjusted_quantity).
    """
    # 1. Session Profit Lock check
    profit_lock = TRADING.get("session_profit_lock", 0)
    if profit_lock > 0 and store.realized_pnl >= profit_lock:
        return False, f"Session profit lock triggered (Realized: ₹{store.realized_pnl:.2f} >= Limit: ₹{profit_lock})", quantity

    # Fetch today's trades for frequency and cooldown checks
    today_trades = await db.get_today_trades()

    # 2. Max Trades per Symbol per Day check
    max_trades = TRADING.get("max_trades_per_symbol", 0)
    if max_trades > 0:
        symbol_trades = [t for t in today_trades if t.get("instrument") == instrument]
        if len(symbol_trades) >= max_trades:
            return False, f"Max trades per symbol reached ({len(symbol_trades)}/{max_trades} for {instrument})", quantity

    # 3. Consecutive Loss Cooldown check
    loss_limit = TRADING.get("consecutive_loss_limit", 0)
    if loss_limit > 0:
        closed_today = [t for t in today_trades if t.get("exit_time") is not None]
        closed_today.sort(key=lambda t: t["exit_time"])
        if len(closed_today) >= loss_limit:
            last_n = closed_today[-loss_limit:]
            all_losses = all((t.get("pnl_final") or 0.0) <= 0 for t in last_n)
            if all_losses:
                last_exit_str = last_n[-1]["exit_time"]
                try:
                    last_exit = datetime.fromisoformat(last_exit_str)
                    if last_exit.tzinfo is None:
                        last_exit = IST.localize(last_exit)
                    
                    now = datetime.now(IST)
                    elapsed_mins = (now - last_exit).total_seconds() / 60.0
                    cooldown_dur = TRADING.get("cooldown_duration_minutes", 120)
                    if elapsed_mins < cooldown_dur:
                        remaining = cooldown_dur - elapsed_mins
                        return False, f"Consecutive loss cooldown active ({remaining:.1f} mins remaining)", quantity
                except Exception as e:
                    print(f"[risk] Cooldown parse error: {e}")

    # 4. Per-Trade Risk Cap & Position Sizing
    max_risk = TRADING.get("max_risk_per_trade", 0)
    if max_risk > 0 and entry_price > sl_price:
        risk_per_unit = entry_price - sl_price
        initial_risk = risk_per_unit * quantity
        if initial_risk > max_risk:
            lot_size = LOT_SIZES.get(instrument, 75)
            max_allowed_qty = max_risk / risk_per_unit
            allowed_lots = int(max_allowed_qty // lot_size)
            if allowed_lots < 1:
                return False, f"Trade risk (₹{initial_risk:.2f}) exceeds max risk cap (₹{max_risk}) even at 1 lot.", quantity
            
            adjusted_quantity = allowed_lots * lot_size
            return True, f"Quantity resized from {quantity} to {adjusted_quantity} to respect ₹{max_risk} per-trade risk limit", adjusted_quantity

    return True, "All risk checks passed", quantity


def classify_signal_quality(decision: dict, premarket_bias: dict, vix: float = 15.0) -> dict:
    """
    Classifies a trading signal:
    - Quality score: 0 to 100
    - Label: STRONG, WEAK, or AVOID
    """
    confidence = decision.get("confidence", 0)
    action = decision.get("action", "NO_TRADE")
    bias = premarket_bias.get("bias", "NEUTRAL")
    
    if action not in ("BUY_CE", "BUY_PE"):
        return {"score": 0, "label": "AVOID", "reason": "No entry action"}

    # Base score is confidence * 10
    score = confidence * 10
    
    # Premarket alignment check
    aligned = False
    if action == "BUY_CE" and bias == "BULLISH":
        aligned = True
    elif action == "BUY_PE" and bias == "BEARISH":
        aligned = True
        
    if aligned:
        score += 15
    elif bias != "NEUTRAL":
        score -= 20

    # VIX adjustment
    if vix > 22.0:
        score -= 10
    elif 12.0 <= vix <= 18.0:
        score += 5
        
    score = max(0, min(100, score))
    
    if score >= 75:
        label = "STRONG"
    elif score >= 50:
        label = "WEAK"
    else:
        label = "AVOID"
        
    return {
        "score": score,
        "label": label,
        "reason": f"Confidence: {confidence}/10, Aligned with Premarket: {aligned}, VIX: {vix:.1f}"
    }
