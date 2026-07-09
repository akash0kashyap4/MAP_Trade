#!/usr/bin/env python3
"""
Cron entry: 06:30 IST every day.
Pings Claude CLI to warm up the session, so the 08:30 premarket call is fast.
Skips on weekends and NSE holidays.
"""
from __future__ import annotations
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

# Load .env so config can read it (cron has no shell env)
env_path = HERE / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

from config import is_market_day  # noqa: E402

CLAUDE_BIN = os.getenv("CLAUDE_BIN", "/usr/bin/claude")


def main() -> int:
    now = datetime.now().isoformat()
    if not is_market_day():
        print(f"[warmup] {now} skipped - NSE closed today")
        return 0
    try:
        out = subprocess.run(
            [CLAUDE_BIN, "-p", "Good morning. Reply with exactly the word READY and nothing else.",
             "--output-format", "text"],
            stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace",
        )
        print(f"[warmup] {now} rc={out.returncode} reply={out.stdout.strip()[:50]}")
        return out.returncode
    except subprocess.TimeoutExpired:
        print(f"[warmup] {now} TIMEOUT")
        return 2
    except Exception as e:
        print(f"[warmup] {now} ERROR {e}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
