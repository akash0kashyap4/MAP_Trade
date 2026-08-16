"""CLI for the practical free stack.

yfinance -> pandas-ta -> Plotly/mplfinance -> Claude

Usage:
    python -m scripts.stack RELIANCE.NS
    python -m scripts.stack TCS.NS --chart both --llm
    python -m scripts.stack ^NSEI --period 1y --interval 1d --chart mplfinance
"""
from __future__ import annotations

import argparse
import asyncio
import json


async def _run(args):
    from ai.stack import full_stack

    agent = None
    if args.llm:
        try:
            from ai.agent import TradingAgent
            agent = TradingAgent()
        except Exception as e:
            print(f"(LLM disabled — could not init TradingAgent: {e})")

    result = await full_stack(
        args.symbol,
        period=args.period,
        interval=args.interval,
        chart=args.chart,
        agent=agent,
    )
    print(json.dumps(result, indent=2, default=str))


def main():
    p = argparse.ArgumentParser(description="Free stack: yfinance + pandas-ta + Plotly/mplfinance + Claude")
    p.add_argument("symbol")
    p.add_argument("--period", default="6mo")
    p.add_argument("--interval", default="1d")
    p.add_argument("--chart", choices=["plotly", "mplfinance", "both", "none"], default="plotly")
    p.add_argument("--llm", action="store_true")
    asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    main()
