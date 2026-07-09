#!/usr/bin/env python3
"""
Cron entry: 04:00 IST every day.
Checks if Groww API is connected successfully and sends a status update
to Telegram so you know the bot is ready for the day.
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

from groww.oauth import check_api_connection, send_telegram
from config import is_market_day

def main() -> int:
    if not is_market_day():
        print(f"[groww-health-cron] {datetime.now().isoformat()} skipped - NSE closed today")
        return 0

    status = check_api_connection()
    if status.get("status") == "connected":
        msg = "Good morning. Ragi is ready. Groww API: Connected"
    else:
        msg = f"WARNING: Groww API connection failed! Check GROWW_API_KEY. Error: {status.get('message')}"

    ok = send_telegram(msg)
    print(f"[groww-health-cron] telegram sent: {ok} at {datetime.now().isoformat()}")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
