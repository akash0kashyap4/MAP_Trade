#!/usr/bin/env python3
"""
Bitcoin Trading Bot — Main Entry Point
Self-learning autonomous trading bot using Claude AI as decision brain
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from data.database import Database
from exchange.binance_client import BinanceClient
from bot.trader import LiveTrader
from ai.agent import AIAgent
from api.routes import router as api_router

# ======================== LOGGING SETUP ========================
logging.basicConfig(
    level=config.LOGGING["level"],
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(config.LOGGING["file"]),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ======================== GLOBAL INSTANCES ========================
db: Database = None
exchange: BinanceClient = None
trader: LiveTrader = None
ai_agent: AIAgent = None
scheduler: AsyncIOScheduler = None


async def init_components():
    """Initialize all bot components on startup"""
    global db, exchange, trader, ai_agent, scheduler

    logger.info("🚀 Initializing Bitcoin Bot components...")

    # 1. Database
    db = Database(config.DATA["db_path"])
    await db.init()
    logger.info("✓ Database initialized")

    # 2. Exchange (Binance)
    exchange = BinanceClient(
        api_key=config.EXCHANGE["api_key"],
        api_secret=config.EXCHANGE["api_secret"],
        testnet=config.EXCHANGE["testnet"],
    )
    await exchange.connect()
    logger.info("✓ Exchange connected (Binance)")

    # 3. AI Agent (Claude)
    ai_agent = AIAgent(
        model=config.AI["model"],
        claude_bin=config.AI["claude_bin"],
        timeout_sec=config.AI["timeout_sec"],
    )
    logger.info(f"✓ AI Agent initialized ({config.AI['model']})")

    # 4. Live Trader
    trader = LiveTrader(
        exchange=exchange,
        db=db,
        ai_agent=ai_agent,
        config=config.TRADING,
    )
    logger.info("✓ Live Trader initialized")

    # 5. Scheduler
    scheduler = AsyncIOScheduler()
    setup_scheduler()
    scheduler.start()
    logger.info("✓ Scheduler started")

    logger.info("✅ All components ready! Trading bot online.")


async def shutdown_components():
    """Cleanup on shutdown"""
    logger.info("🛑 Shutting down bot...")

    if scheduler:
        scheduler.shutdown()
    if trader:
        await trader.close()
    if exchange:
        await exchange.disconnect()
    if db:
        await db.close()

    logger.info("✅ Bot shutdown complete")


def setup_scheduler():
    """Configure APScheduler jobs for market ticks, EOD, learning"""

    # Market tick every 5 minutes (24/7 for crypto)
    scheduler.add_job(
        market_tick_job,
        "interval",
        minutes=config.TRADING["decision_interval"],
        id="market_tick",
        replace_existing=True,
    )
    logger.info(f"📅 Market tick scheduled every {config.TRADING['decision_interval']}m")

    # EOD square-off at 23:55 UTC (optional for crypto)
    scheduler.add_job(
        eod_job,
        "cron",
        hour=23,
        minute=55,
        id="eod_squareoff",
        replace_existing=True,
    )
    logger.info("📅 EOD square-off scheduled at 23:55 UTC")

    # Nightly learning at 03:00 UTC (post-market analysis)
    scheduler.add_job(
        learning_job,
        "cron",
        hour=3,
        minute=0,
        id="nightly_learning",
        replace_existing=True,
    )
    logger.info("📅 Nightly learning scheduled at 03:00 UTC")


async def market_tick_job():
    """Called every 5 minutes: fetch data, get AI decision, execute trade"""
    try:
        logger.debug("🔄 Market tick starting...")

        # Fetch latest market data
        market_data = await exchange.get_market_data(config.TRADING["pairs"][0])

        # Get AI decision
        decision = await trader.get_ai_decision(market_data)

        if decision and decision.get("action") != "HOLD":
            # Execute trade
            await trader.execute_trade(decision)

        # Check trailing SL on existing positions
        await trader.check_trailing_stops()

        logger.debug("✓ Market tick complete")
    except Exception as e:
        logger.error(f"❌ Market tick error: {e}", exc_info=True)


async def eod_job():
    """Called at 23:55 UTC: square off all positions and log daily stats"""
    try:
        logger.info("🌙 EOD square-off starting...")
        await trader.square_off_all()
        daily_stats = await db.get_daily_stats()
        logger.info(f"📊 Daily stats: {daily_stats}")
    except Exception as e:
        logger.error(f"❌ EOD error: {e}", exc_info=True)


async def learning_job():
    """Called at 03:00 UTC: nightly self-learning from trades"""
    try:
        logger.info("🧠 Nightly learning starting...")

        # Get last 30 days of trades
        trades = await db.get_trades_since(days=30)

        if len(trades) > 5:  # Only learn if enough trades
            suggestions = await ai_agent.learn_from_trades(trades)

            # Store suggestions in DB for dashboard review
            await db.store_learning_suggestions(suggestions)
            logger.info(f"💡 Learning complete: {len(suggestions)} suggestions")
        else:
            logger.info(f"⏭️ Skipping learning: only {len(trades)} trades")

    except Exception as e:
        logger.error(f"❌ Learning error: {e}", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context: startup + shutdown"""
    # Startup
    await init_components()
    yield
    # Shutdown
    await shutdown_components()


# ======================== FASTAPI APP ========================
app = FastAPI(
    title="Bitcoin Trading Bot API",
    description="Autonomous trading bot powered by Claude AI",
    version="1.0.0",
    lifespan=lifespan,
)

# Include API routes
app.include_router(api_router)


# ======================== MANUAL ENDPOINTS ========================
@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "exchange": "binance",
        "paper_trade": config.TRADING["paper_trade"],
    }


@app.post("/api/tick")
async def manual_tick():
    """Manually trigger one market tick"""
    await market_tick_job()
    return {"status": "tick_executed"}


@app.post("/api/learn/run-now")
async def manual_learning():
    """Manually trigger nightly learning"""
    await learning_job()
    return {"status": "learning_executed"}


@app.post("/api/eod/run-now")
async def manual_eod():
    """Manually trigger EOD square-off"""
    await eod_job()
    return {"status": "eod_executed"}


# ======================== MAIN ========================
if __name__ == "__main__":
    import uvicorn

    logger.info("=" * 60)
    logger.info("Bitcoin Trading Bot Starting")
    logger.info(f"Exchange: {config.EXCHANGE['name']}")
    logger.info(f"Paper Trade: {config.TRADING['paper_trade']}")
    logger.info(f"AI Model: {config.AI['model']}")
    logger.info("=" * 60)

    uvicorn.run(
        app,
        host=config.API["host"],
        port=config.API["port"],
        log_level=config.LOGGING["level"].lower(),
    )
