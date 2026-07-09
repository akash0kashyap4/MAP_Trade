from config import TRADING, LOT_SIZES


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
