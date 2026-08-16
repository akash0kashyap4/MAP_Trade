"""MAP TRADE Brain orchestrator — one entrypoint that runs research + chart-read +
sentiment + a quick backtest for a symbol, and returns a single bundle.

LLM steps are optional; if no agent is passed you still get numbers.
"""
from __future__ import annotations

import asyncio

from ai.chart_ai import chart_ai_read, chart_snapshot
from ai.research import research_symbol
from backtest.quick import compare_strategies


async def full_brain(
    symbol: str,
    agent=None,
    period: str = "1y",
    interval: str = "1d",
    with_backtest: bool = True,
) -> dict:
    """Run every capability against one symbol. Never raises — errors captured per-section."""
    async def _safe(coro, label):
        try:
            return await coro
        except Exception as e:
            return {"error": f"{label}: {e}"}

    async def _thread(fn, label):
        try:
            return await asyncio.to_thread(fn)
        except Exception as e:
            return {"error": f"{label}: {e}"}

    chart_coro = chart_ai_read(symbol, agent, period=period, interval=interval) \
        if agent else asyncio.to_thread(chart_snapshot, symbol, period, interval)

    tasks = [
        _safe(research_symbol(symbol, agent=agent), "research"),
        _safe(chart_coro, "chart"),
    ]
    if with_backtest:
        tasks.append(_thread(lambda: compare_strategies(symbol, period=period, interval=interval), "backtest"))

    results = await asyncio.gather(*tasks)
    bundle = {
        "symbol": symbol,
        "research": results[0],
        "chart": results[1],
    }
    if with_backtest:
        bundle["backtest"] = results[2]
    return bundle
