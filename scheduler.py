from __future__ import annotations
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler

IST = pytz.timezone("Asia/Kolkata")


def setup_scheduler(trader, learner) -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone=IST)

    sched.add_job(
        trader.premarket_analysis,
        "cron",
        day_of_week="mon-fri",
        hour=8,
        minute=30,
        id="premarket",
    )

    # Fires just after market open (09:15). If the 08:30 premarket plan / news
    # analysis didn't complete, this alerts immediately instead of the failure
    # being discovered at end-of-day review.
    sched.add_job(
        trader.pipeline_health_check,
        "cron",
        day_of_week="mon-fri",
        hour=9,
        minute=16,
        id="pipeline_health",
    )

    sched.add_job(
        trader.market_loop_tick,
        "cron",
        day_of_week="mon-fri",
        hour="9-15",
        minute="15,20,25,30,35,40,45,50,55,0,5,10",
        id="market_tick",
    )

    sched.add_job(
        trader.end_of_day,
        "cron",
        day_of_week="mon-fri",
        hour=15,
        minute=20,
        id="eod",
    )

    sched.add_job(
        learner.run_nightly_review,
        "cron",
        hour=21,
        minute=0,
        id="nightly_learn",
    )

    sched.add_job(
        learner.weekly_review,
        "cron",
        day_of_week="sun",
        hour=10,
        minute=0,
        id="weekly_review",
    )

    return sched
