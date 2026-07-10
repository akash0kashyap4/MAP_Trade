"""
Groww Live Feed — yFinance based REST polling loop.
Fetches Nifty, BankNifty, Sensex LTPs every 10 seconds via yfinance.
Used as fallback when Groww API market data access is restricted.
"""
from __future__ import annotations
import asyncio
from data.store import store

# yFinance symbols for NSE indices
_YF_SYMBOLS = {
    "NIFTY":     "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "SENSEX":    "^BSESN",
}

_yf_session = None

def _get_yf_session():
    global _yf_session
    if _yf_session is None:
        try:
            from curl_cffi import requests as _cf
            _yf_session = _cf.Session(impersonate="chrome")
        except ImportError:
            _yf_session = False  # no curl_cffi — use bare yfinance
    return _yf_session


def _fetch_all_ltps() -> dict[str, float]:
    """Fetch current LTP for all indices using yfinance fast_info."""
    results = {}
    try:
        import yfinance as yf
        session = _get_yf_session()

        for instrument, yf_symbol in _YF_SYMBOLS.items():
            try:
                ticker = yf.Ticker(yf_symbol, session=session) if session else yf.Ticker(yf_symbol)
                # fast_info is much faster than history()
                info = ticker.fast_info
                ltp = getattr(info, "last_price", None) or getattr(info, "regularMarketPrice", None)
                if ltp and float(ltp) > 0:
                    results[instrument] = float(ltp)
                    # Try setting previous close
                    prev_close = getattr(info, "previous_close", None)
                    if prev_close and float(prev_close) > 0:
                        store.set_prev_close(instrument, float(prev_close))
                    continue

                # Fallback: 1-day history, last close
                hist = ticker.history(period="1d", interval="1m")
                if not hist.empty:
                    results[instrument] = float(hist["Close"].iloc[-1])
                    # Try setting previous close from yesterday's history
                    if len(hist) > 1:
                        store.set_prev_close(instrument, float(hist["Close"].iloc[0]))
            except Exception as e:
                print(f"[groww.feed] yf error {instrument}: {e}")

    except ImportError:
        print("[groww.feed] yfinance not installed — pip install yfinance")

    return results


async def start_feed():
    """
    Continuously polls index prices every 10 seconds via yfinance.
    Updates store.prices, store.today_candles, store.indicators, and store.feed_status.
    """
    print("[groww.feed] Starting yFinance polling feed (Nifty / BankNifty / Sensex)...")
    store.feed_status = "connecting"
    counter = 0

    while True:
        try:
            loop = asyncio.get_running_loop()
            ltps = await loop.run_in_executor(None, _fetch_all_ltps)

            if ltps:
                for instrument, ltp in ltps.items():
                    store.update_price(instrument, ltp)
                store.feed_status = "live"
                print("[groww.feed] Prices: " +
                      " | ".join(f"{k}={v:,.2f}" for k, v in ltps.items()))

                # Periodically (every 6 ticks = 60 seconds) fetch candles & calculate indicators
                if counter % 6 == 0:
                    try:
                        from datetime import datetime
                        import pytz
                        from config import INSTRUMENTS
                        from groww.historical import get_index_candles, get_india_vix
                        from indicators.calculator import calculate_all

                        IST = pytz.timezone("Asia/Kolkata")
                        today_str = datetime.now(IST).strftime("%Y-%m-%d")

                        # Update India VIX
                        vix = await loop.run_in_executor(None, get_india_vix)
                        store.india_vix = vix

                        for inst, key in INSTRUMENTS.items():
                            candles = await loop.run_in_executor(None, get_index_candles, key, today_str)
                            if candles:
                                candles.sort(key=lambda c: c[0])
                                store.update_candles(inst, candles)
                                indicators = calculate_all(candles)
                                if indicators:
                                    store.update_indicators(inst, indicators)
                    except Exception as poll_candles_err:
                        print(f"[groww.feed] error updating candles/indicators: {poll_candles_err}")

                counter += 1

                # Broadcast to all SSE clients so dashboard updates in real-time
                try:
                    from routers.sse import broadcast
                    await broadcast(store.sse_payload())
                except Exception as bcast_err:
                    print(f"[groww.feed] broadcast error: {bcast_err}")
            else:
                store.feed_status = "error"

        except Exception as e:
            print(f"[groww.feed] Poll error: {e}")
            store.feed_status = "error"

        await asyncio.sleep(10)  # 10s — yfinance is slower than REST


def request_option_subscribe(instrument_key: str):
    """No-op — REST polling only."""
    pass
