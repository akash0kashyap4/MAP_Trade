from __future__ import annotations
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bot.health_monitor import check_jobs_health

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

    # Feature 1: health check fires at 09:15 — alerts if morning jobs failed
    from bot.trader import _send_telegram as _tg
    async def _health_check():
        await check_jobs_health(telegram_fn=_tg)

    sched.add_job(
        _health_check,
        "cron",
        day_of_week="mon-fri",
        hour=9,
        minute=15,
        id="health_check",
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
