"""
Bulk historical data downloader — downloads spot + option candles from Upstox
and caches them in the local SQLite DB so backtests run without repeated API calls.

Usage (standalone):
    python -m upstox.data_loader --instrument NIFTY --from 2025-01-01 --to 2025-03-31

Usage (from API):
    POST /api/data/download  { "instrument": "NIFTY", "date_from": "...", "date_to": "...", "type": "both" }
"""
from __future__ import annotations
import time
from datetime import datetime, timedelta, date

from config import REQUEST_DELAY, INSTRUMENTS, ATM_STEP, SENSEX_STEP
from upstox.historical import (
    get_index_candles, get_expired_expiries,
    get_expired_option_key, get_expired_option_candles,
    is_trading_day, find_nearest_expiry, round_to_atm,
)
from data.candle_cache import save_candles, has_candles, get_cache_stats


def download_spot_history(instrument: str, date_from: str, date_to: str) -> dict:
    """
    Download 1-min spot candles for every trading day in range.
    Skips dates already cached. Returns stats dict.
    """
    instrument_key = INSTRUMENTS.get(instrument)
    if not instrument_key:
        return {"error": f"Unknown instrument: {instrument}"}

    start = datetime.strptime(date_from, "%Y-%m-%d").date()
    end   = datetime.strptime(date_to,   "%Y-%m-%d").date()
    downloaded, skipped, failed = 0, 0, 0
    current = start

    print(f"[loader] Downloading {instrument} spot candles {date_from} to {date_to}")
    while current <= end:
        if is_trading_day(current):
            ds = current.strftime("%Y-%m-%d")
            if has_candles(instrument_key, ds):
                skipped += 1
            else:
                candles = get_index_candles(instrument_key, ds)
                if candles:
                    save_candles(instrument_key, candles)
                    downloaded += 1
                    print(f"  spot {ds}: {len(candles)} candles cached")
                else:
                    failed += 1
                time.sleep(REQUEST_DELAY)
        current += timedelta(days=1)

    print(f"[loader] Spot done — downloaded={downloaded} skipped={skipped} failed={failed}")
    return {"downloaded": downloaded, "skipped": skipped, "failed": failed, "instrument": instrument}


def download_option_history(
    instrument: str,
    date_from: str,
    date_to: str,
    option_types: tuple = ("CE", "PE"),
) -> dict:
    """
    Download 1-min ATM option candles for every trading day in range.
    Uses Upstox expired-instruments API for past data.
    Skips dates already cached. Returns stats dict.
    """
    instrument_key = INSTRUMENTS.get(instrument)
    if not instrument_key:
        return {"error": f"Unknown instrument: {instrument}"}

    step  = SENSEX_STEP if instrument == "SENSEX" else ATM_STEP
    start = datetime.strptime(date_from, "%Y-%m-%d").date()
    end   = datetime.strptime(date_to,   "%Y-%m-%d").date()

    print(f"[loader] Fetching expiry list for {instrument}...")
    expiries = get_expired_expiries(instrument_key)
    if not expiries:
        return {"error": f"No expiry data returned for {instrument}"}
    print(f"[loader] {len(expiries)} expiries found")

    downloaded, skipped, failed = 0, 0, 0
    current = start

    print(f"[loader] Downloading {instrument} option candles {date_from} to {date_to}")
    while current <= end:
        if not is_trading_day(current):
            current += timedelta(days=1)
            continue

        ds = current.strftime("%Y-%m-%d")

        # Get spot open to determine ATM strike
        spot_candles = get_index_candles(instrument_key, ds)
        time.sleep(REQUEST_DELAY)
        if not spot_candles:
            print(f"  {ds}: no spot candles — skipping")
            current += timedelta(days=1)
            continue

        spot_open  = float(spot_candles[0][1])
        atm_strike = round_to_atm(spot_open, step)
        expiry     = find_nearest_expiry(expiries, ds) or ds

        for otype in option_types:
            opt_key = get_expired_option_key(instrument_key, expiry, atm_strike, otype)
            time.sleep(REQUEST_DELAY)

            if not opt_key:
                print(f"  {ds} {atm_strike}{otype} exp={expiry}: no instrument key")
                failed += 1
                continue

            if has_candles(opt_key, ds):
                skipped += 1
                continue

            candles = get_expired_option_candles(opt_key, ds)
            time.sleep(REQUEST_DELAY)

            if candles:
                save_candles(opt_key, candles)
                downloaded += 1
                print(f"  {ds} {atm_strike}{otype} exp={expiry} [{opt_key}]: {len(candles)} candles")
            else:
                print(f"  {ds} {atm_strike}{otype} exp={expiry}: no candles returned")
                failed += 1

        current += timedelta(days=1)

    print(f"[loader] Options done — downloaded={downloaded} skipped={skipped} failed={failed}")
    return {"downloaded": downloaded, "skipped": skipped, "failed": failed, "instrument": instrument}


def download_all(instrument: str, date_from: str, date_to: str) -> dict:
    """Download both spot and ATM option candles for a date range."""
    spot_stats   = download_spot_history(instrument, date_from, date_to)
    option_stats = download_option_history(instrument, date_from, date_to)
    return {"spot": spot_stats, "options": option_stats}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Download historical candle data from Upstox")
    parser.add_argument("--instrument", default="NIFTY", choices=["NIFTY", "BANKNIFTY", "SENSEX"])
    parser.add_argument("--from",    dest="date_from", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--to",      dest="date_to",   required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--type",    default="both",   choices=["spot", "options", "both"])
    args = parser.parse_args()

    if args.type in ("spot", "both"):
        download_spot_history(args.instrument, args.date_from, args.date_to)
    if args.type in ("options", "both"):
        download_option_history(args.instrument, args.date_from, args.date_to)

    print("\n--- Cache Stats ---")
    for row in get_cache_stats():
        print(f"  {row['instrument']}: {row['days']} days, {row['candles']} candles")
