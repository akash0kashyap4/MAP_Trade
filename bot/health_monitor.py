"""
Feature 1: Automated health check — fires alert if premarket or news job
fails to complete by 09:15 IST (market open). No more discovering failures
retroactively at EOD review.
"""
from __future__ import annotations
import asyncio
from datetime import datetime
import pytz

IST = pytz.timezone("Asia/Kolkata")

# Flags set by the jobs themselves when they successfully complete
_premarket_ran_today: str = ""   # stores date string "YYYY-MM-DD"
_news_ran_today: str = ""


def mark_premarket_ran():
    global _premarket_ran_today
    _premarket_ran_today = datetime.now(IST).strftime("%Y-%m-%d")


def mark_news_ran():
    global _news_ran_today
    _news_ran_today = datetime.now(IST).strftime("%Y-%m-%d")


async def check_jobs_health(telegram_fn=None):
    """
    Called at 09:15 IST (market open). Alerts immediately if premarket or
    news jobs did not complete this morning.
    """
    today = datetime.now(IST).strftime("%Y-%m-%d")
    issues = []

    if _premarket_ran_today != today:
        issues.append("⚠️ PREMARKET ANALYSIS did not run this morning!")
    if _news_ran_today != today:
        issues.append("⚠️ NEWS SCAN did not run this morning!")

    if issues:
        msg = "🚨 Ragi Health Alert @ Market Open\n" + "\n".join(issues)
        print(f"[health] {msg}")
        if telegram_fn:
            await telegram_fn(msg)
    else:
        print("[health] All morning jobs completed successfully ✓")
