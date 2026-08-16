"""Per-symbol research: price snapshot + fundamentals + news + sentiment.

Uses free sources only: yfinance, RSS feeds already wired in ai/news.py.
Optional LLM summary via the existing TradingAgent plumbing.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytz

from ai.news import fetch_headlines
from ai.sentiment import score_symbol_headlines, score_headlines

IST = pytz.timezone("Asia/Kolkata")


def _price_snapshot(symbol: str) -> dict:
    """Pull last 60 daily candles + key stats from yfinance. Never raises."""
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        hist = t.history(period="3mo", interval="1d")
        if hist.empty:
            return {"error": "no price data"}
        last = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) > 1 else last
        high_52 = hist["High"].tail(252).max() if len(hist) > 20 else hist["High"].max()
        low_52 = hist["Low"].tail(252).min() if len(hist) > 20 else hist["Low"].min()
        info = {}
        try:
            info = t.fast_info or {}
        except Exception:
            info = {}
        return {
            "symbol": symbol,
            "close": round(float(last["Close"]), 2),
            "change_pct": round((float(last["Close"]) / float(prev["Close"]) - 1) * 100, 2),
            "volume": int(last["Volume"]),
            "high_range": round(float(high_52), 2),
            "low_range": round(float(low_52), 2),
            "market_cap": int(info.get("market_cap") or 0) or None,
            "currency": info.get("currency"),
        }
    except Exception as e:
        return {"error": f"yfinance: {e}"}


def _fundamentals(symbol: str) -> dict:
    """Best-effort fundamentals via yfinance.info. Skip fields that fail."""
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info or {}
    except Exception as e:
        return {"error": f"info: {e}"}
    keys = [
        "sector", "industry", "trailingPE", "forwardPE", "priceToBook",
        "dividendYield", "returnOnEquity", "profitMargins", "debtToEquity",
        "revenueGrowth", "earningsGrowth", "recommendationKey", "targetMeanPrice",
    ]
    return {k: info.get(k) for k in keys if info.get(k) is not None}


async def research_symbol(symbol: str, agent=None) -> dict:
    """Full research bundle for one symbol. `agent` optional for LLM summary."""
    price_task = asyncio.to_thread(_price_snapshot, symbol)
    fund_task = asyncio.to_thread(_fundamentals, symbol)
    news_task = fetch_headlines(max_per_feed=8)
    price, fundamentals, headlines = await asyncio.gather(price_task, fund_task, news_task)

    symbol_sent = score_symbol_headlines(symbol, headlines)
    market_sent = score_headlines(headlines)

    bundle = {
        "symbol": symbol,
        "as_of": datetime.now(IST).isoformat(timespec="seconds"),
        "price": price,
        "fundamentals": fundamentals,
        "sentiment_symbol": symbol_sent,
        "sentiment_market": market_sent,
        "headlines_sample": [h["headline"] for h in headlines[:10]],
    }

    if agent is not None:
        bundle["ai_summary"] = await _llm_summary(agent, bundle)
    return bundle


async def _llm_summary(agent, bundle: dict) -> str:
    system = (
        "You are a sober Indian equities analyst. Given a data bundle, "
        "give a 5-line verdict: (1) trend, (2) valuation, (3) news read, "
        "(4) key risk, (5) actionable stance (accumulate / hold / avoid). "
        "No hype. No price targets."
    )
    import json
    user = f"Symbol: {bundle['symbol']}\n\nBundle:\n{json.dumps(bundle, default=str)[:6000]}"
    try:
        return (await agent._ask(system, user)) or ""
    except Exception as e:
        return f"(llm error: {e})"
