#!/usr/bin/env python3
"""
Cron entry: 04:00 IST every day.
Checks Groww API connection and sends a Telegram status ping.
Groww uses long-lived API keys — no daily OAuth login required.
"""
from __future__ import annotations
import os
import sys
from datetime import datetime
from pathlib import Path

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
        print(f"[daily-check-cron] {datetime.now().isoformat()} skipped - NSE closed today")
        return 0

    result = check_api_connection()
    if result["ok"]:
        msg = (
            f"Good morning. Ragi is ready.\n"
            f"Groww API: Connected\n"
            f"Dashboard: https://akash.mehakva.com\n"
            f"Time: {datetime.now().strftime('%H:%M IST')}"
        )
    else:
        msg = (
            f"WARNING: Groww API connection failed!\n"
            f"Error: {result['message']}\n"
            f"Check GROWW_API_KEY and GROWW_SECRET_KEY in .env"
        )

    ok = send_telegram(msg)
    print(f"[daily-check-cron] telegram sent: {ok} at {datetime.now().isoformat()}")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
