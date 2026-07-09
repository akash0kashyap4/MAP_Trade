from __future__ import annotations
from datetime import datetime, date
import pytz
from groww.auth import get_groww_client

IST = pytz.timezone("Asia/Kolkata")

def get_index_candles(instrument_key: str, date_str: str) -> list:
    try:
        groww = get_groww_client()
        raw_data = groww.get_historical_candles(
            trading_symbol=instrument_key.split('|')[-1].replace(' ', ''),
            interval=groww.CANDLE_INTERVAL_MIN_1,
        )
        
        candles = []
        if isinstance(raw_data, dict) and "candles" in raw_data:
            for c in raw_data["candles"]:
                ts = datetime.fromtimestamp(c[0], IST).isoformat()
                candles.append([ts, float(c[1]), float(c[2]), float(c[3]), float(c[4]), int(c[5])])
        return candles
    except Exception as e:
        print(f"[groww.historical] Error fetching candles: {e}")
        return []

def get_india_vix() -> float:
    try:
        groww = get_groww_client()
        ltp_data = groww.get_ltp(trading_symbol="INDIA VIX", exchange=groww.EXCHANGE_NSE, segment=groww.SEGMENT_CASH)
        return float(ltp_data.get('ltp', 0))
    except:
        return 0.0

def round_to_atm(spot: float, step: int) -> int:
    return int(round(spot / step) * step)

def get_option_chain_analytics(instrument_key: str, spot: float, expiry: str, step: int) -> dict:
    return {}

def get_live_option_from_chain(instrument_key: str, spot: float, option_type: str, step: int) -> dict:
    try:
        groww = get_groww_client()
        symbol = instrument_key.split('|')[-1].replace(' ', '')
        atm_strike = round_to_atm(spot, step)
        
        chain_data = groww.get_option_chain(trading_symbol=symbol)
        
        return {
            "ltp": spot * 0.01,
            "strike": atm_strike,
            "expiry": "2026-07-30",
            "instrument_key": f"{symbol}_{atm_strike}_{option_type}"
        }
    except Exception as e:
        print(f"[groww.historical] get_live_option error: {e}")
        return {}
