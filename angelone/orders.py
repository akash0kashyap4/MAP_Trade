"""
AngelOne SmartAPI order placement helpers.

All functions are synchronous (SmartApi SDK is sync).
Call these from asyncio code via asyncio.to_thread().

Symbol format for options:
  AngelOne uses a token-based system. You must look up the instrument token
  from the scrip master CSV before placing an order.

  Example:
    symbol = "NIFTY09JAN2524500CE"   ← exchange symbol
    token  = "35003"                  ← instrument token (from scrip master)
    exch   = "NFO"

Scrip master: https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json
"""
from __future__ import annotations
import json
import requests
from SmartApi.smartExceptions import DataException
from angelone.auth import get_angel_client

SCRIP_MASTER_URL = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)

_scrip_cache: list[dict] | None = None


# ── Scrip master ──────────────────────────────────────────────────────────────

def _load_scrip_master() -> list[dict]:
    global _scrip_cache
    if _scrip_cache is None:
        resp = requests.get(SCRIP_MASTER_URL, timeout=20)
        resp.raise_for_status()
        _scrip_cache = resp.json()
    return _scrip_cache


def find_option_token(
    index: str,
    expiry_ddmmmyyyy: str,
    strike: int,
    option_type: str,          # "CE" or "PE"
) -> tuple[str, str]:
    """
    Return (symbol, token) for the given option leg.

    Args:
        index            : "NIFTY" | "BANKNIFTY" | "SENSEX"
        expiry_ddmmmyyyy : e.g. "09JAN25"  ← 7-char format from scrip master
        strike           : e.g. 24500
        option_type      : "CE" or "PE"

    Returns:
        (tradingsymbol, token)  ← both strings
    """
    exch = "BFO" if index == "SENSEX" else "NFO"
    target_name = f"{index}{expiry_ddmmmyyyy}{strike}{option_type}"

    master = _load_scrip_master()
    for row in master:
        if row.get("exch_seg") == exch and row.get("symbol") == target_name:
            return row["symbol"], row["token"]

    raise ValueError(
        f"Option not found in scrip master: {target_name} on {exch}. "
        f"Check expiry format (use 7-char: 09JAN25)."
    )


# ── Order placement ───────────────────────────────────────────────────────────

def place_market_order(
    tradingsymbol: str,
    token: str,
    quantity: int,
    transaction_type: str,     # "BUY" or "SELL"
    exchange: str = "NFO",     # "NFO" | "BFO"
    product: str = "INTRADAY", # "INTRADAY" | "CARRYFORWARD"
) -> str:
    """
    Place a market order. Returns order_id string.
    Raises on failure.
    """
    client = get_angel_client()

    order_params = {
        "variety":          "NORMAL",
        "tradingsymbol":    tradingsymbol,
        "symboltoken":      token,
        "transactiontype":  transaction_type,
        "exchange":         exchange,
        "ordertype":        "MARKET",
        "producttype":      product,
        "duration":         "DAY",
        "quantity":         str(quantity),
        "price":            "0",
        "squareoff":        "0",
        "stoploss":         "0",
    }

    resp = client.placeOrder(order_params)

    if not resp.get("status"):
        raise RuntimeError(f"AngelOne placeOrder failed: {resp.get('message', resp)}")

    order_id = resp["data"]["orderid"]
    return order_id


def place_limit_order(
    tradingsymbol: str,
    token: str,
    quantity: int,
    transaction_type: str,
    price: float,
    exchange: str = "NFO",
    product: str = "INTRADAY",
) -> str:
    """Place a limit order. Returns order_id."""
    client = get_angel_client()

    order_params = {
        "variety":          "NORMAL",
        "tradingsymbol":    tradingsymbol,
        "symboltoken":      token,
        "transactiontype":  transaction_type,
        "exchange":         exchange,
        "ordertype":        "LIMIT",
        "producttype":      product,
        "duration":         "DAY",
        "quantity":         str(quantity),
        "price":            str(round(price, 1)),
        "squareoff":        "0",
        "stoploss":         "0",
    }

    resp = client.placeOrder(order_params)

    if not resp.get("status"):
        raise RuntimeError(f"AngelOne placeOrder (LIMIT) failed: {resp.get('message', resp)}")

    return resp["data"]["orderid"]


def get_order_status(order_id: str) -> dict:
    """
    Returns dict with keys: status, fill_price, quantity, message.
    status values: 'complete' | 'open' | 'rejected' | 'cancelled'
    """
    client = get_angel_client()
    resp = client.orderBook()

    if not resp.get("status"):
        raise RuntimeError(f"orderBook failed: {resp.get('message')}")

    orders = resp.get("data") or []
    for o in orders:
        if o.get("orderid") == order_id:
            return {
                "status":     o.get("orderstatus", "").lower(),
                "fill_price": float(o.get("averageprice") or 0),
                "quantity":   int(o.get("filledshares") or 0),
                "message":    o.get("text", ""),
                "raw":        o,
            }

    raise ValueError(f"order_id {order_id} not found in order book")


def cancel_order(order_id: str, variety: str = "NORMAL") -> bool:
    """Cancel an open order. Returns True if accepted."""
    client = get_angel_client()
    resp = client.cancelOrder(order_id, variety)
    return bool(resp.get("status"))


def get_positions() -> list[dict]:
    """Return current open positions from AngelOne."""
    client = get_angel_client()
    resp = client.position()
    if not resp.get("status"):
        raise RuntimeError(f"position() failed: {resp.get('message')}")
    return resp.get("data") or []


def get_funds() -> dict:
    """Return available funds / margin."""
    client = get_angel_client()
    resp = client.rmsLimit()
    if not resp.get("status"):
        raise RuntimeError(f"rmsLimit() failed: {resp.get('message')}")
    return resp.get("data", {})
