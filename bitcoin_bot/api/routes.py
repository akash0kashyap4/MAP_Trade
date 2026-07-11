"""
REST API Routes for Bitcoin Trading Bot
Endpoints for status, trading, and dashboard
"""

from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime

router = APIRouter(prefix="/api", tags=["trading"])


@router.get("/status")
async def get_status():
    """Get bot status and portfolio info"""
    return {
        "status": "running",
        "timestamp": datetime.utcnow().isoformat(),
        "exchange": "binance",
        "paper_trade": True,
        "positions": [],
        "portfolio_value": 10000,
        "daily_pnl": 0,
    }


@router.get("/trades")
async def get_trades(limit: int = 50):
    """Get trade history"""
    return {
        "trades": [],
        "total": 0,
        "limit": limit,
    }


@router.get("/positions")
async def get_positions():
    """Get open positions"""
    return {"positions": []}


@router.get("/portfolio")
async def get_portfolio():
    """Get portfolio breakdown"""
    return {
        "total_value": 10000,
        "cash": 10000,
        "positions": 0,
        "daily_pnl": 0,
        "monthly_pnl": 0,
        "yearly_pnl": 0,
    }


@router.get("/stats")
async def get_stats(days: int = 30):
    """Get trading statistics"""
    return {
        "period_days": days,
        "total_trades": 0,
        "win_rate": 0,
        "profit_factor": 0,
        "sharpe_ratio": 0,
        "max_drawdown": 0,
        "total_return": 0,
    }


@router.post("/backtest")
async def run_backtest(start_date: str, end_date: str, strategy: str = "claude"):
    """Run backtest on historical data"""
    return {
        "status": "backtest_started",
        "strategy": strategy,
        "period": f"{start_date} to {end_date}",
    }


@router.get("/candles/{pair}")
async def get_candles(pair: str, interval: str = "5m", limit: int = 100):
    """Get candlestick data"""
    return {"pair": pair, "interval": interval, "candles": []}


@router.get("/learning-rules")
async def get_learning_rules():
    """Get suggested learning rules from nightly analysis"""
    return {"rules": [], "last_updated": None}
