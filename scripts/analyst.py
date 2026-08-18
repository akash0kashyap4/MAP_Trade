"""MAP Trade Analyst CLI — the best-quality one-shot analysis.

Usage:
    python -m scripts.analyst RELIANCE.NS --llm
    python -m scripts.analyst TCS.NS --period 2y
    python -m scripts.analyst ^NSEI --no-save
"""
from __future__ import annotations

import argparse
import asyncio


async def _run(args):
    from ai.analyst import analyze

    agent = None
    if args.llm:
        try:
            from ai.agent import TradingAgent
            agent = TradingAgent()
        except Exception as e:
            print(f"(LLM disabled — {e})")

    result = await analyze(
        args.symbol,
        agent=agent,
        period=args.period,
        interval=args.interval,
        save_report=not args.no_save,
    )
    if "error" in result:
        print(f"ERROR: {result['error']}")
        return
    print(result["report_md"])
    if result.get("report_path"):
        print(f"\n_Saved: {result['report_path']}_")


def main():
    p = argparse.ArgumentParser(description="MAP Trade Analyst — the best one-shot analysis")
    p.add_argument("symbol")
    p.add_argument("--period", default="1y")
    p.add_argument("--interval", default="1d")
    p.add_argument("--llm", action="store_true", help="Include Claude synthesis section")
    p.add_argument("--no-save", action="store_true")
    asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    main()
