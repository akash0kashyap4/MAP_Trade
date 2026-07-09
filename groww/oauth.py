"""
Groww API utility functions.
"""
from __future__ import annotations
import os
import requests
from groww.auth import get_groww_client

def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()

def check_api_connection() -> dict:
    """Check if the Groww API is connected successfully."""
    try:
        client = get_groww_client()
        if client:
            return {"status": "connected", "message": "Groww API is ready."}
        return {"status": "failed", "message": "Failed to initialize Groww client."}
    except Exception as e:
        return {"status": "failed", "message": str(e)}

def send_telegram(text: str) -> bool:
    """Fire-and-forget Telegram alert. Returns True if delivered."""
    bot   = _env("TELEGRAM_BOT_TOKEN")
    chat  = _env("TELEGRAM_CHAT_ID")
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
