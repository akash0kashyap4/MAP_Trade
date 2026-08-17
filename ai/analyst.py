"""MAP Trade Analyst — the best-quality one-shot analysis.

Combines every capability into a single markdown-formatted verdict:
    fetch (yfinance)
      -> indicators (pandas-ta)
      -> chart (Plotly HTML + mplfinance PNG)
      -> news + sentiment (RSS + lexicon)
      -> backtest (3 vectorized strategies)
      -> LLM synthesis (Claude, single call over the whole bundle)

Output: a dict with {report_md, chart_paths, raw} — the report_md is what a
human actually reads; raw is everything under the hood for auditing.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytz

from ai.news import fetch_headlines
from ai.sentiment import score_headlines, score_symbol_headlines
from ai.stack import add_indicators, fetch_ohlcv, render_mplfinance, render_plotly, _last_snapshot
from backtest.quick import compare_strategies

IST = pytz.timezone("Asia/Kolkata")
REPORT_DIR = Path(os.getenv("RAGI_REPORT_DIR", "data/reports"))
CHART_DIR = Path(os.getenv("RAGI_CHART_DIR", "data/charts"))


SYNTHESIS_SYSTEM = """You are MAP Trade Analyst — a disciplined Indian markets desk.

Given a data bundle (price snapshot, indicators, news sentiment, backtest of
3 mechanical strategies on the same symbol), produce a crisp markdown report
with these exact sections:

## Verdict
One line: ACCUMULATE / HOLD / AVOID / SHORT — with 1-sentence reason.

## Trend & Momentum
2-3 lines. Reference specific indicator values.

## Levels
Support, resistance, invalidation as concrete numbers.

## News & Sentiment
2 lines. What the tape is saying vs what the news is saying.

## Backtest Read
Which of the 3 strategies actually worked on this symbol historically; is the
edge real or noise (compare Sharpe + drawdown vs buy-and-hold)?

## Actionable Trigger
One if-then: "If price does X, enter Y with SL at Z, target A."

## Risks
Top 2 risks in 1 line each.

Rules: no hedging, no disclaimers, no price targets pulled from thin air. If
data is missing say "insufficient data" for that section — never make it up."""


async def _synthesize(agent, bundle: dict) -> str:
    if agent is None:
        return "_(LLM disabled — pass --llm or an agent to get the synthesis)_"
    user = f"Symbol: {bundle['symbol']}\n\nBundle JSON:\n{json.dumps(bundle, default=str)[:9000]}"
    try:
        return (await agent._ask(SYNTHESIS_SYSTEM, user)) or "_(empty response)_"
    except Exception as e:
        return f"_(llm error: {e})_"


def _format_report(symbol: str, bundle: dict, synthesis: str) -> str:
    snap = bundle["snapshot"]
    sent = bundle["sentiment_symbol"]
    market_sent = bundle["sentiment_market"]
    bt = bundle["backtest"]
    charts = bundle["charts"]
    stamp = bundle["as_of"]

    def _fmt_bt(row: dict) -> str:
        m = row.get("strategy_metrics", {})
        bh = row.get("buyhold_metrics", {})
        return (
            f"| {row['strategy']} | {m.get('total_return_pct', 0)}% | "
            f"{m.get('sharpe', 0)} | {m.get('max_drawdown_pct', 0)}% | "
            f"{m.get('trades', 0)} | vs B&H {bh.get('total_return_pct', 0)}% |"
        )

    lines = [
        f"# MAP Trade Analyst — {symbol}",
        f"_As of {stamp}_",
        "",
        "## Snapshot",
        f"- Close: **{snap.get('close')}**  ({snap.get('change_pct', 0):+.2f}%)",
        f"- Range: {snap.get('period_low')} – {snap.get('period_high')}",
        f"- SMA20 / SMA50: {snap.get('sma20')} / {snap.get('sma50')}",
        f"- RSI(14): {snap.get('rsi')}    ATR(14): {snap.get('atr')}",
        f"- MACD: {snap.get('macd')} / signal {snap.get('macd_signal')}",
        "",
        "## Sentiment",
        f"- Symbol-specific ({sent.get('matched', 0)} headlines): "
        f"**{sent.get('label')}** ({sent.get('score'):+d})",
        f"- Overall market ({market_sent.get('total', 0)} headlines): "
        f"**{market_sent.get('label')}** ({market_sent.get('score'):+d})",
    ]
    if sent.get("top_positive"):
        lines.append("- Top bullish: " + "; ".join(h["headline"] for h in sent["top_positive"][:2]))
    if sent.get("top_negative"):
        lines.append("- Top bearish: " + "; ".join(h["headline"] for h in sent["top_negative"][:2]))

    lines += [
        "",
        "## Backtest (5y daily, 5 bps cost)",
        "| strategy | return | sharpe | maxDD | trades | benchmark |",
        "|---|---|---|---|---|---|",
    ]
    for row in bt if isinstance(bt, list) else []:
        lines.append(_fmt_bt(row))

    lines += ["", "## Charts"]
    for kind, path in charts.items():
        lines.append(f"- **{kind}**: `{path}`")

    lines += ["", "## AI Synthesis", "", synthesis]
    return "\n".join(lines)


async def analyze(
    symbol: str,
    agent=None,
    period: str = "1y",
    interval: str = "1d",
    save_report: bool = True,
) -> dict:
    """The best-quality analysis. Every step guarded; never raises."""
    now = datetime.now(IST)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    safe = symbol.replace("/", "_").replace("^", "")

    # 1. data + indicators
    try:
        df = add_indicators(fetch_ohlcv(symbol, period=period, interval=interval))
        snap = _last_snapshot(df)
    except Exception as e:
        return {"error": f"data: {e}", "symbol": symbol}

    # 2. charts (both formats — Plotly for humans, PNG for LLM/reports)
    charts: dict[str, str] = {}
    for label, fn, ext in [
        ("plotly", render_plotly, "html"),
        ("mplfinance", render_mplfinance, "png"),
    ]:
        try:
            p = fn(df, symbol, CHART_DIR / f"{safe}_{stamp}.{ext}")
            charts[label] = str(p)
        except Exception as e:
            charts[f"{label}_error"] = str(e)

    # 3. news + sentiment (both symbol-scoped and overall)
    try:
        headlines = await fetch_headlines(max_per_feed=8)
    except Exception as e:
        headlines = []
        snap["news_error"] = str(e)
    sym_sent = score_symbol_headlines(symbol, headlines)
    mkt_sent = score_headlines(headlines)

    # 4. backtest (3 strategies on the same symbol)
    try:
        bt = compare_strategies(symbol, period="5y", interval="1d")
    except Exception as e:
        bt = [{"error": f"backtest: {e}"}]

    bundle = {
        "symbol": symbol,
        "as_of": now.isoformat(timespec="seconds"),
        "period": period,
        "interval": interval,
        "snapshot": snap,
        "charts": charts,
        "sentiment_symbol": sym_sent,
        "sentiment_market": mkt_sent,
        "backtest": bt,
        "top_headlines": [h["headline"] for h in headlines[:8]],
        "bars": len(df),
    }

    # 5. LLM synthesis over the whole bundle
    synthesis = await _synthesize(agent, bundle)
    report_md = _format_report(symbol, bundle, synthesis)

    report_path = None
    if save_report:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        report_path = REPORT_DIR / f"{safe}_{stamp}.md"
        report_path.write_text(report_md, encoding="utf-8")

    return {
        "symbol": symbol,
        "report_md": report_md,
        "report_path": str(report_path) if report_path else None,
        "chart_paths": charts,
        "raw": bundle,
    }
