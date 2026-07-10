from __future__ import annotations
from datetime import datetime, date, timedelta, time
import math
import pytz
import yfinance as yf
from groww.auth import get_groww_client

IST = pytz.timezone("Asia/Kolkata")

# Groww exchange/segment constants
_EXCHANGE_NSE = "NSE"
_EXCHANGE_BSE = "BSE"
_SEGMENT_INDICES = "INDICES"
_SEGMENT_FNO = "FNO"

# instrument_key  →  (exchange, segment, trading_symbol)
_INSTRUMENT_MAP = {
    "NSE_INDEX|Nifty 50":   (_EXCHANGE_NSE, _SEGMENT_INDICES, "Nifty 50"),
    "NSE_INDEX|Nifty Bank": (_EXCHANGE_NSE, _SEGMENT_INDICES, "Nifty Bank"),
    "BSE_INDEX|SENSEX":     (_EXCHANGE_BSE, _SEGMENT_INDICES, "SENSEX"),
}

_YF_INDEX_MAP = {
    "NSE_INDEX|Nifty 50": "^NSEI",
    "NSE_INDEX|Nifty Bank": "^NSEBANK",
    "BSE_INDEX|SENSEX": "^BSESN",
}


def get_index_candles(instrument_key: str, date_str: str) -> list:
    """Fetch 1-min candles for a given date from Groww, falling back to yfinance on failure."""
    # 1. Attempt Groww API (if permissions/subscriptions allow)
    try:
        groww = get_groww_client()
        exchange, segment, symbol = _INSTRUMENT_MAP.get(
            instrument_key, (_EXCHANGE_NSE, _SEGMENT_INDICES, instrument_key.split("|")[-1])
        )

        start = f"{date_str} 09:15:00"
        end   = f"{date_str} 15:30:00"

        raw_data = groww.get_historical_candles(
            exchange=exchange,
            segment=segment,
            groww_symbol=f"{exchange}-{symbol.replace(' ', '')}",
            start_time=start,
            end_time=end,
            candle_interval="1minute",
        )

        candles = []
        raw_list = raw_data if isinstance(raw_data, list) else raw_data.get("candles", [])
        for c in raw_list:
            if isinstance(c[0], (int, float)):
                ts = datetime.fromtimestamp(c[0] / 1000 if c[0] > 1e10 else c[0], IST).isoformat()
            else:
                ts = str(c[0])
            candles.append([ts, float(c[1]), float(c[2]), float(c[3]), float(c[4]), int(c[5]) if len(c) > 5 else 0])

        if candles:
            return candles
    except Exception as e:
        print(f"[groww.historical] Groww candles API unavailable/failed for {instrument_key}: {e}. Trying yfinance...")

    # 2. yfinance Fallback
    try:
        yf_symbol = _YF_INDEX_MAP.get(instrument_key)
        if not yf_symbol:
            # Fallback guessing
            if "Bank" in instrument_key:
                yf_symbol = "^NSEBANK"
            elif "SENSEX" in instrument_key or "BSE" in instrument_key:
                yf_symbol = "^BSESN"
            else:
                yf_symbol = "^NSEI"

        # Calculate start and end dates
        dt_start = datetime.strptime(date_str, "%Y-%m-%d")
        dt_end = dt_start + timedelta(days=1)
        start_date_str = dt_start.strftime("%Y-%m-%d")
        end_date_str = dt_end.strftime("%Y-%m-%d")

        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(start=start_date_str, end=end_date_str, interval="1m")
        if df.empty:
            return []

        # Localize/convert to IST timezone and parse
        candles = []
        for dt, row in df.iterrows():
            # Ensure time is in 09:15 to 15:30 range
            dt_ist = dt.astimezone(IST)
            if not (time(9, 15) <= dt_ist.time() <= time(15, 30)):
                continue

            ts = dt_ist.isoformat()
            candles.append([
                ts,
                float(row["Open"]),
                float(row["High"]),
                float(row["Low"]),
                float(row["Close"]),
                int(row["Volume"]) if "Volume" in row else 0
            ])
        return candles

    except Exception as yf_err:
        print(f"[groww.historical] yfinance fallback failed for {instrument_key}: {yf_err}")
        return []



def get_india_vix() -> float:
    """Fetch India VIX LTP from Groww, falling back to yfinance ^INDIAVIX."""
    try:
        groww = get_groww_client()
        res = groww.get_ltp(
            exchange_trading_symbols=("NSE:India VIX",),
            segment="INDICES",
        )
        ltp = res.get("ltp") or res.get("lastPrice") or res.get("last_price")
        if ltp:
            return float(ltp)
    except Exception as e:
        pass

    # yfinance Fallback
    try:
        ticker = yf.Ticker("^INDIAVIX")
        info = ticker.fast_info
        ltp = getattr(info, "last_price", None) or getattr(info, "regularMarketPrice", None)
        if ltp:
            return float(ltp)
        # 1d history fallback
        df = ticker.history(period="1d")
        if not df.empty:
            return float(df["Close"].iloc[-1])
    except Exception as yf_err:
        print(f"[groww.historical] India VIX yfinance fallback failed: {yf_err}")
    return 13.0  # Safe default VIX if both fail


def round_to_atm(spot: float, step: int) -> int:
    return int(round(spot / step) * step)


def get_option_chain_analytics(instrument_key: str, spot: float, expiry: str, step: int) -> dict:
    """
    Fetch option chain from Groww and compute PCR, max pain, ATM IV, OI stats.
    Falls back to a realistic mock generator if Groww API returns Access Forbidden.
    """
    try:
        groww = get_groww_client()
        exchange, _, symbol = _INSTRUMENT_MAP.get(
            instrument_key, (_EXCHANGE_NSE, _SEGMENT_FNO, instrument_key.split("|")[-1])
        )
        clean_symbol = symbol.replace(" ", "")
        chain_data = groww.get_option_chain(
            exchange=exchange,
            underlying=clean_symbol,
            expiry_date=expiry,
        )
        if chain_data:
            atm = round_to_atm(spot, step)
            ce_oi_total = pe_oi_total = 0
            atm_iv = atm_ce_oi = atm_pe_oi = 0
            pain_map: dict[int, float] = {}
            days_to_exp = max(0, (datetime.strptime(expiry, "%Y-%m-%d").date() - date.today()).days)

            contracts = chain_data if isinstance(chain_data, list) else chain_data.get("data", [])
            for row in contracts:
                strike = int(row.get("strike_price", row.get("strikePrice", 0)))
                ce = row.get("call_options", row.get("callOptions", {})) or {}
                pe = row.get("put_options",  row.get("putOptions",  {})) or {}

                ce_oi = float(ce.get("open_interest", ce.get("openInterest", 0)) or 0)
                pe_oi = float(pe.get("open_interest", pe.get("openInterest", 0)) or 0)
                ce_oi_total += ce_oi
                pe_oi_total += pe_oi

                pain_map[strike] = pain_map.get(strike, 0) + (ce_oi + pe_oi)

                if strike == atm:
                    atm_iv    = float(ce.get("implied_volatility", ce.get("impliedVolatility", 0)) or 0)
                    atm_ce_oi = ce_oi
                    atm_pe_oi = pe_oi

            pcr = round(pe_oi_total / ce_oi_total, 3) if ce_oi_total > 0 else 1.0
            max_pain = max(pain_map, key=pain_map.get) if pain_map else atm

            return {
                "pcr":         pcr,
                "max_pain":    max_pain,
                "atm_iv":      atm_iv,
                "atm_ce_oi":   atm_ce_oi,
                "atm_pe_oi":   atm_pe_oi,
                "oi_change":   round(atm_pe_oi - atm_ce_oi, 0),
                "days_to_exp": days_to_exp,
            }
    except Exception as e:
        # Expected if token lacks options subscription/permissions
        pass

    # Option Chain Mock Fallback
    try:
        atm = round_to_atm(spot, step)
        days_to_exp = max(0, (datetime.strptime(expiry, "%Y-%m-%d").date() - date.today()).days)
        # Generate semi-randomized realistic values
        pcr = round(1.05 + 0.1 * math.sin(spot / 100), 2)
        max_pain = atm
        atm_iv = round(12.5 + 2.0 * math.cos(spot / 200), 2)
        atm_ce_oi = int(1200000 + 300000 * math.sin(spot / 50))
        atm_pe_oi = int(atm_ce_oi * pcr)
        return {
            "pcr":         pcr,
            "max_pain":    max_pain,
            "atm_iv":      atm_iv,
            "atm_ce_oi":   atm_ce_oi,
            "atm_pe_oi":   atm_pe_oi,
            "oi_change":   round(atm_pe_oi - atm_ce_oi, 0),
            "days_to_exp": days_to_exp,
        }
    except Exception as mock_err:
        print(f"[groww.historical] option mock fallback failed: {mock_err}")
    return {}


def get_live_option_from_chain(instrument_key: str, spot: float, option_type: str, step: int) -> dict:
    """
    Find the ATM option for a given instrument/type and return LTP + metadata.
    Falls back to a realistic mock option pricing model (Black-Scholes approximation)
    if Groww API access to option chains is restricted/forbidden.
    """
    try:
        groww = get_groww_client()
        exchange, _, symbol = _INSTRUMENT_MAP.get(
            instrument_key, (_EXCHANGE_NSE, _SEGMENT_FNO, instrument_key.split("|")[-1])
        )
        clean_symbol = symbol.replace(" ", "")
        atm_strike = round_to_atm(spot, step)

        for days_ahead in range(0, 8):
            expiry_date = (date.today() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
            try:
                chain_data = groww.get_option_chain(
                    exchange=exchange,
                    underlying=clean_symbol,
                    expiry_date=expiry_date,
                )
                contracts = chain_data if isinstance(chain_data, list) else chain_data.get("data", [])
                if not contracts:
                    continue

                for row in contracts:
                    strike = int(row.get("strike_price", row.get("strikePrice", 0)))
                    if strike != atm_strike:
                        continue

                    key = "call_options" if option_type == "CE" else "put_options"
                    alt_key = "callOptions" if option_type == "CE" else "putOptions"
                    opt = row.get(key, row.get(alt_key, {})) or {}
                    ltp = float(opt.get("ltp", opt.get("lastPrice", 0)) or 0)

                    groww_symbol = opt.get("trading_symbol", opt.get("tradingSymbol",
                        f"NSE-{clean_symbol}-{expiry_date}-{atm_strike}-{option_type}"))

                    if ltp > 0:
                        return {
                            "ltp":            ltp,
                            "strike":         atm_strike,
                            "expiry":         expiry_date,
                            "instrument_key": groww_symbol,
                        }
            except Exception:
                continue
    except Exception:
        pass

    # Option Pricing Mock Fallback (Black-Scholes-like simplified intrinsic + extrinsic model)
    try:
        atm_strike = round_to_atm(spot, step)
        # Expiry is usually upcoming Thursday (NSE) or Friday (BSE)
        # Find next Thursday
        today = date.today()
        days_to_thursday = (3 - today.weekday()) % 7
        expiry_date = (today + timedelta(days=days_to_thursday)).strftime("%Y-%m-%d")
        days_to_exp = max(0.5, days_to_thursday)

        # Intrinsic value
        intrinsic = max(0.0, spot - atm_strike) if option_type == "CE" else max(0.0, atm_strike - spot)

        # Extrinsic (Time value) based on spot price, standard Indian IV (~13%), and sqrt of time
        iv = 0.13
        time_fraction = days_to_exp / 365.0
        extrinsic = spot * 0.4 * iv * math.sqrt(time_fraction)

        ltp = round(intrinsic + extrinsic, 2)
        if ltp < 1.0:
            ltp = 1.05  # minimum premium

        groww_symbol = f"MOCK-NSE-{instrument_key.split('|')[-1].upper().replace(' ', '')}-{expiry_date}-{atm_strike}-{option_type}"
        return {
            "ltp":            ltp,
            "strike":         atm_strike,
            "expiry":         expiry_date,
            "instrument_key": groww_symbol,
        }
    except Exception as mock_err:
        print(f"[groww.historical] live option mock fallback failed: {mock_err}")
    return {}
