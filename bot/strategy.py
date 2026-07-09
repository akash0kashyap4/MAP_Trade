from __future__ import annotations
from indicators.calculator import calculate_all, resample_5min, calculate_price_structure
from config import TRADING

# Last N 5-min candles sent to Claude = 60 minutes of context
CANDLE_WINDOW = 12


def build_market_context(
    instrument: str,
    spot_candles: list,
    spot_price: float,
    prev_close: float,
    options_snapshot: dict,
    open_positions: list,
    today_pnl: float,
    premarket_bias: dict,
    time_of_day: str,
    historical_win_rate: float = 0.0,
    capital_info: dict = None,
) -> dict:
    # Resample 1-min → 5-min, take last 60 min (12 bars)
    candles_5m = resample_5min(spot_candles)
    candles_for_claude = candles_5m[-CANDLE_WINDOW:] if len(candles_5m) >= CANDLE_WINDOW else candles_5m

    # Compute indicators from full 1-min series for accuracy, display from 5-min
    indicators = calculate_all(spot_candles)
    price_structure = calculate_price_structure(candles_5m)  # full session, not just display window
    spot_change_pct = ((spot_price - prev_close) / prev_close * 100) if prev_close else 0.0

    return {
        "instrument":                instrument,
        "spot_price":                spot_price,
        "spot_change_pct":           round(spot_change_pct, 2),
        "last_10_candles":           candles_for_claude,
        "indicators":                indicators,
        "price_structure":           price_structure,
        "options_snapshot":          options_snapshot,
        "open_positions":            open_positions,
        "today_pnl":                 today_pnl,
        "premarket_bias":            premarket_bias,
        "time_of_day":               time_of_day,
        "historical_win_rate_similar": historical_win_rate,
        "capital_info":              capital_info or {},
    }


def is_valid_trade_time(time_str: str) -> bool:
    h, m = map(int, time_str.split(":"))
    total = h * 60 + m
    return 9 * 60 + 15 <= total <= 15 * 60 + 0
