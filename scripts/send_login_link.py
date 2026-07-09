#!/usr/bin/env python3
"""
Cron entry: 04:00 IST every day.
Sends a Telegram message containing today's Upstox OAuth URL.
User taps once on phone, gets fingerprint-authenticated, and the
callback endpoint stores the new token automatically.
"""
from __future__ import annotations
import os
import sys
from datetime import datetime
from pathlib import Path

# Allow running outside venv by adding repo root to path
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

# Manually load .env (script runs from cron without shell env)
env_path = HERE / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

from groww.oauth import build_login_url, send_telegram
from config import is_market_day


def main() -> int:
    if not is_market_day():
        print(f"[token-refresh-cron] {datetime.now().isoformat()} skipped - NSE closed today")
        return 0

    url = build_login_url(state=datetime.now().strftime("%Y%m%d"))
    msg = (
        "Good morning. Tap to refresh Ragi's Upstox token:\n\n"
        f"{url}\n\n"
        "Fingerprint/PIN login on phone -> auto-saves the token -> bot restarts."
    )
    ok = send_telegram(msg)
    print(f"[token-refresh-cron] telegram sent: {ok} at {datetime.now().isoformat()}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
