from __future__ import annotations
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler

IST = pytz.timezone("Asia/Kolkata")


def setup_scheduler(trader, learner, news_brain=None, reporter=None,
                    notify_fn=None) -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone=IST)

    # News scan BEFORE premarket so the 08:30 plan already knows today's news
    if news_brain is not None:
        sched.add_job(
            news_brain.scan,
            "cron",
            day_of_week="mon-fri",
            hour=8,
            minute=15,
            id="news_morning",
            kwargs={"notify_fn": notify_fn},
        )
        sched.add_job(
            news_brain.scan,
            "cron",
            day_of_week="mon-fri",
            hour=12,
            minute=30,
            id="news_midday",
        )

    sched.add_job(
        trader.premarket_analysis,
        "cron",
        day_of_week="mon-fri",
        hour=8,
        minute=30,
        id="premarket",
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

    # Daily self-review report after square-off (15:20 EOD → 15:45 report)
    if reporter is not None:
        sched.add_job(
            reporter.generate,
            "cron",
            day_of_week="mon-fri",
            hour=15,
            minute=45,
            id="daily_report",
            kwargs={"notify_fn": notify_fn},
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
