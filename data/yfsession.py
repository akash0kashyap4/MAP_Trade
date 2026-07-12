"""
Shared yfinance access with curl_cffi browser impersonation.

Yahoo Finance blocks bare requests coming from datacenter / cloud IPs
(DigitalOcean, AWS, …). That is why the chart's /api/candles returned nothing on
the production droplet while the exact same symbols worked from a laptop. Routing
every yfinance call through a curl_cffi Chrome-impersonation session gets past
that block. Every part of the app that touches yfinance should import `ticker`
from here so the impersonation is applied consistently (chart, premarket cues,
India VIX).
"""
from __future__ import annotations

try:
    import yfinance as yf
    _YF_OK = True
except Exception:                       # pragma: no cover - yfinance optional in CI
    yf = None
    _YF_OK = False

try:
    from curl_cffi import requests as _cf_requests
    _SESSION = _cf_requests.Session(impersonate="chrome")
except Exception:                       # pragma: no cover - curl_cffi optional in CI
    _SESSION = None


def yf_available() -> bool:
    return _YF_OK


def has_impersonation() -> bool:
    return _SESSION is not None


def ticker(symbol: str):
    """Return a yfinance Ticker that impersonates a browser when possible."""
    if not _YF_OK:
        raise RuntimeError("yfinance is not installed")
    return yf.Ticker(symbol, session=_SESSION) if _SESSION else yf.Ticker(symbol)
