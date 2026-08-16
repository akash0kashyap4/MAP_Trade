"""CLI for the Ragi Brain.

Usage:
    python -m scripts.brain RELIANCE.NS
    python -m scripts.brain TCS.NS --no-backtest
    python -m scripts.brain ^NSEI --interval 1d --period 6mo
    python -m scripts.brain HDFCBANK.NS --llm     # include Claude summary
"""
from __future__ import annotations

import argparse
import asyncio
import json


async def _run(args):
    from ai.brain import full_brain

    agent = None
    if args.llm:
        try:
            from ai.agent import TradingAgent
            agent = TradingAgent()
        except Exception as e:
            print(f"(LLM disabled — could not init TradingAgent: {e})")

    result = await full_brain(
        args.symbol,
        agent=agent,
        period=args.period,
        interval=args.interval,
        with_backtest=not args.no_backtest,
    )
    print(json.dumps(result, indent=2, default=str))


def main():
    p = argparse.ArgumentParser(description="Ragi Brain — research + chart + sentiment + backtest")
    p.add_argument("symbol", help="e.g. RELIANCE.NS, ^NSEI, TCS.NS")
    p.add_argument("--period", default="1y")
    p.add_argument("--interval", default="1d")
    p.add_argument("--no-backtest", action="store_true")
    p.add_argument("--llm", action="store_true", help="Also run Claude summaries")
    asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    main()
