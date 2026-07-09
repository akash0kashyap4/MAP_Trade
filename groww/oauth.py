"""
Groww API utility functions.

Groww uses long-lived API key + secret (no daily OAuth flow).
Daily health check at 04:00 IST sends a Telegram status ping confirming
the API connection is alive.
"""
from __future__ import annotations
import os
import requests


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def check_api_connection() -> dict:
    """Validate that GROWW_API_KEY + GROWW_SECRET_KEY are working."""
    from groww.auth import get_groww_client
    try:
        get_groww_client()
        return {"ok": True, "message": "Groww API connected successfully."}
    except Exception as e:
        return {"ok": False, "message": str(e)}


def send_telegram(text: str) -> bool:
    """Fire-and-forget Telegram alert. Returns True if delivered."""
    bot  = _env("TELEGRAM_BOT_TOKEN")
    chat = _env("TELEGRAM_CHAT_ID")
    if not bot or not chat:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{bot}/sendMessage",
            json={"chat_id": chat, "text": text, "disable_web_page_preview": False},
            timeout=10,
        )
        return r.status_code == 200
    except Exception:
        return False
