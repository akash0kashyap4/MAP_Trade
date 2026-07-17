"""
NSE India data client — no official API, uses browser-impersonation session.

Provides:
  get_option_chain(symbol)          — real PCR, max pain, ATM IV, OI
  get_index_history(symbol, f, t)   — daily OHLCV for NIFTY / BANKNIFTY
"""
from __future__ import annotations
import time
import urllib.parse
from datetime import date, datetime
from typing import Optional

import requests

_BASE = "https://www.nseindia.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer":         f"{_BASE}/",
    "Connection":      "keep-alive",
    "DNT":             "1",
}

_INDEX_MAP = {
    "NIFTY":     "NIFTY 50",
    "NIFTY50":   "NIFTY 50",
    "BANKNIFTY": "NIFTY BANK",
    "SENSEX":    "S&P BSE SENSEX",
}

_OC_SYMBOL_MAP = {
    "NIFTY":     "NIFTY",
    "BANKNIFTY": "BANKNIFTY",
}

_ATM_STEP = {"NIFTY": 50, "BANKNIFTY": 100}


class NSEClient:
    _session:   Optional[requests.Session] = None
    _last_init: float = 0
    _SESSION_TTL = 270  # refresh cookies every 4.5 min

    # ── session management ────────────────────────────────────────────────────

    def _get_session(self) -> requests.Session:
        now = time.time()
        if self._session is None or (now - self._last_init) > self._SESSION_TTL:
            s = requests.Session()
            s.headers.update(_HEADERS)
            try:
                # warm-up: hit homepage to obtain NSE session cookies
                s.get(f"{_BASE}/", timeout=12)
                time.sleep(0.6)
                s.get(f"{_BASE}/market-data/live-equity-market", timeout=10)
                time.sleep(0.3)
            except Exception:
                pass
            self._session = s
            self._last_init = now
        return self._session

    def _get(self, path: str, retries: int = 2) -> dict:
        s = self._get_session()
        for attempt in range(retries + 1):
            try:
                r = s.get(f"{_BASE}{path}", timeout=12)
                if r.status_code == 401 or r.status_code == 403:
                    # Force session refresh and retry once
                    self._session = None
                    s = self._get_session()
                    continue
                r.raise_for_status()
                return r.json()
            except (requests.exceptions.JSONDecodeError, ValueError):
                raise ConnectionError("NSE returned non-JSON response")
            except requests.exceptions.RequestException as e:
                if attempt == retries:
                    raise ConnectionError(f"NSE request failed: {e}")
                time.sleep(1.5 * (attempt + 1))
        return {}

    # ── Option Chain ──────────────────────────────────────────────────────────

    def get_option_chain(self, symbol: str) -> dict:
        """
        Fetch live option chain from NSE and compute analytics.

        Returns:
          symbol, spot, pcr, max_pain, atm, atm_iv,
          atm_ce_oi, atm_pe_oi, oi_change,
          ce_oi_total, pe_oi_total, nearest_expiry
        """
        sym = symbol.upper().replace(" ", "")
        nse_sym = _OC_SYMBOL_MAP.get(sym, sym)

        data = self._get(f"/api/option-chain-indices?symbol={nse_sym}")

        records   = data.get("records") or {}
        spot      = float(records.get("underlyingValue") or 0)
        expiries  = records.get("expiryDates") or []
        nearest   = expiries[0] if expiries else None
        rows      = records.get("data") or []

        step = _ATM_STEP.get(sym, 50)
        atm  = round(spot / step) * step

        ce_oi_total = pe_oi_total = 0
        atm_iv = atm_ce_oi = atm_pe_oi = 0.0
        pain_map: dict[int, float] = {}

        for row in rows:
            # Only use nearest expiry rows for cleaner PCR
            if nearest and row.get("expiryDate") != nearest:
                continue
            strike = int(row.get("strikePrice") or 0)
            ce     = row.get("CE") or {}
            pe     = row.get("PE") or {}

            c_oi = float(ce.get("openInterest") or 0)
            p_oi = float(pe.get("openInterest") or 0)
            ce_oi_total += c_oi
            pe_oi_total += p_oi

            # Max pain: strike where combined OI loss is highest for option writers
            pain_map[strike] = pain_map.get(strike, 0) + c_oi + p_oi

            if strike == atm:
                atm_iv    = float(ce.get("impliedVolatility") or 0)
                atm_ce_oi = c_oi
                atm_pe_oi = p_oi

        pcr      = round(pe_oi_total / ce_oi_total, 3) if ce_oi_total > 0 else 1.0
        max_pain = max(pain_map, key=pain_map.get) if pain_map else atm

        return {
            "symbol":         sym,
            "spot":           spot,
            "pcr":            pcr,
            "max_pain":       max_pain,
            "atm":            atm,
            "atm_iv":         round(atm_iv, 2),
            "atm_ce_oi":      int(atm_ce_oi),
            "atm_pe_oi":      int(atm_pe_oi),
            "oi_change":      int(atm_pe_oi - atm_ce_oi),
            "ce_oi_total":    int(ce_oi_total),
            "pe_oi_total":    int(pe_oi_total),
            "nearest_expiry": nearest,
        }

    # ── Index Daily History ───────────────────────────────────────────────────

    def get_index_history(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
    ) -> list[dict]:
        """
        Fetch daily OHLCV from NSE for a given index.

        symbol: "NIFTY" | "BANKNIFTY" | "NIFTY 50" | "NIFTY BANK"
        Returns list of {"date", "open", "high", "low", "close", "volume"}
        sorted ascending.
        """
        sym        = symbol.upper().replace(" ", "")
        index_type = _INDEX_MAP.get(sym, symbol)
        path = (
            f"/api/historical/indicesHistory"
            f"?indexType={urllib.parse.quote(index_type)}"
            f"&from={from_date.strftime('%d-%m-%Y')}"
            f"&to={to_date.strftime('%d-%m-%Y')}"
        )

        data = self._get(path)

        rows   = (data.get("data") or {}).get("indexCloseOnlineRecords") or []
        result = []
        for row in rows:
            try:
                d_str = (row.get("EOD_TIMESTAMP") or "")[:10]
                if not d_str:
                    continue
                result.append({
                    "date":   d_str,
                    "open":   float(row.get("EOD_OPEN_INDEX_VAL")  or 0),
                    "high":   float(row.get("EOD_HIGH_INDEX_VAL")  or 0),
                    "low":    float(row.get("EOD_LOW_INDEX_VAL")   or 0),
                    "close":  float(row.get("EOD_CLOSING_INDEX_VAL") or 0),
                    "volume": int(row.get("EOD_TRADED_QTY") or 0),
                })
            except Exception:
                continue

        return sorted(result, key=lambda x: x["date"])


# ── Singleton ─────────────────────────────────────────────────────────────────
_client: Optional[NSEClient] = None


def get_nse_client() -> NSEClient:
    global _client
    if _client is None:
        _client = NSEClient()
    return _client
