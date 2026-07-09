"""
Upstox OAuth helpers.

Daily flow:
  04:00 IST cron job  ->  build_login_url()  ->  Telegram sends URL to user
  User taps URL on phone  ->  Upstox login (fingerprint)  ->  Upstox redirects
  to /api/upstox/callback?code=XYZ  ->  exchange_code_for_token() runs
  ->  writes new UPSTOX_TOKEN to .env  ->  systemctl restart ragi
"""
from __future__ import annotations
import os
import re
import urllib.parse
from pathlib import Path
from typing import Optional

import requests

UPSTOX_AUTH_URL  = "https://api.upstox.com/v2/login/authorization/dialog"
UPSTOX_TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def build_login_url(state: Optional[str] = None) -> str:
    """Construct the OAuth authorize URL the user taps on their phone."""
    params = {
        "response_type": "code",
        "client_id":     _env("UPSTOX_API_KEY"),
        "redirect_uri":  _env("UPSTOX_REDIRECT_URI"),
    }
    if state:
        params["state"] = state
    return f"{UPSTOX_AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code_for_token(code: str) -> dict:
    """POST the OAuth code -> get access_token. Raises on HTTP error."""
    data = {
        "code":          code,
        "client_id":     _env("UPSTOX_API_KEY"),
        "client_secret": _env("UPSTOX_API_SECRET"),
        "redirect_uri":  _env("UPSTOX_REDIRECT_URI"),
        "grant_type":    "authorization_code",
    }
    resp = requests.post(
        UPSTOX_TOKEN_URL,
        data=data,
        headers={"accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def write_token_to_env(token: str, env_path: str = "/opt/ragi/.env") -> None:
    """Atomically update UPSTOX_TOKEN line in .env (creates file if missing)."""
    p = Path(env_path)
    if p.exists():
        text = p.read_text()
        if re.search(r"^UPSTOX_TOKEN=.*$", text, re.MULTILINE):
            new = re.sub(r"^UPSTOX_TOKEN=.*$", f"UPSTOX_TOKEN={token}", text, flags=re.MULTILINE)
        else:
            new = text.rstrip() + f"\nUPSTOX_TOKEN={token}\n"
    else:
        new = f"UPSTOX_TOKEN={token}\n"
    tmp = p.with_suffix(".env.tmp")
    tmp.write_text(new)
    tmp.replace(p)
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass


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
