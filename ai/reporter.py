"""
Ragi Daily Reporter — the bot's end-of-day journal.

Every trading day (15:45 IST) it assembles everything that happened — premarket
plan, news pulse, actual market moves, every trade with its entry reasoning —
and asks Claude to write an honest self-review:

  • per-trade post-mortem (WHY loss / HOW profit, root cause + lesson)
  • knowledge gained (stored in knowledge_base, reused in future prompts)
  • new strategy proposals (stored in ai_strategies → Strategy Lab)
  • feature requests (what data/tools the AI needs to get smarter)

The report persists in daily_reports and renders in the dashboard Reports tab.
If the AI is unreachable, a stats-only report is still saved so no day is lost.
"""
from __future__ import annotations

from datetime import datetime

import pytz

from ai.prompts import DAILY_REPORT_SYSTEM, DAILY_REPORT_USER

IST = pytz.timezone("Asia/Kolkata")

MAX_STRATEGIES_PER_DAY = 1
MAX_SUGGESTIONS = 3
MAX_KNOWLEDGE = 4


def _now_ist() -> datetime:
    return datetime.now(IST)


def _fmt_trades_block(trades: list[dict]) -> str:
    if not trades:
        return "No trades were taken today."
    lines = []
    for t in trades:
        status = "OPEN" if not t.get("exit_time") else ("WIN" if (t.get("pnl_final") or 0) > 0 else "LOSS")
        entry_t = str(t.get("entry_time") or "")[11:16]
        exit_t = str(t.get("exit_time") or "")[11:16] or "--:--"
        lines.append(
            f"[{status}] {t.get('instrument')} {t.get('strike')} {t.get('action')} "
            f"| conf={t.get('confidence')} | in {entry_t} @₹{t.get('entry_price')} "
            f"→ out {exit_t} @₹{t.get('exit_price') or '—'} ({t.get('exit_reason') or 'open'}) "
            f"| P&L=₹{(t.get('pnl_final') or 0):,.0f} | qty={t.get('quantity')}\n"
            f"    entry logic: {(t.get('entry_reason') or 'n/a')[:200]}"
        )
    return "\n".join(lines)


def _fmt_market_block(store) -> str:
    lines = []
    for name, info in store.prices.items():
        if info.ltp > 0:
            lines.append(
                f"{name}: close {info.ltp:,.1f} ({info.chg_pct:+.2f}% vs prev close {info.prev_close:,.1f})"
            )
    if store.india_vix:
        lines.append(f"India VIX: {store.india_vix}")
    return "\n".join(lines) if lines else "Market data unavailable (feed was down)."


def _stats(trades: list[dict]) -> dict:
    closed = [t for t in trades if t.get("exit_time")]
    wins = [t for t in closed if (t.get("pnl_final") or 0) > 0]
    pnl = sum(t.get("pnl_final") or 0 for t in closed)
    fees = sum(t.get("fees_total") or 0 for t in closed)
    return {
        "n_trades": len(trades),
        "n_open": len(trades) - len(closed),
        "closed": len(closed),
        "wins": len(wins),
        "losses": len(closed) - len(wins),
        "win_rate": (len(wins) / len(closed) * 100) if closed else 0.0,
        "realized_pnl": pnl,
        "fees": fees,
    }


class DailyReporter:
    def __init__(self, agent):
        self.agent = agent  # TradingAgent — reuses its Claude plumbing

    async def generate(self, report_date: str | None = None, notify_fn=None) -> dict:
        """Build + persist the daily report. Returns the report dict."""
        from data import database as db
        from data.store import store

        now = _now_ist()
        date = report_date or now.strftime("%Y-%m-%d")
        is_today = date == now.strftime("%Y-%m-%d")

        if is_today:
            trades = await db.get_today_trades()
        else:
            trades = [t for t in await db.get_trades(days=365)
                      if str(t.get("entry_time", ""))[:10] == date]

        stats = _stats(trades)
        news = await db.get_news_analysis(date) or {}
        known = await db.get_knowledge(limit=25)
        mode = store.trading_mode if is_today else "paper"

        report: dict = {
            "date": date,
            "mode": mode,
            "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "stats": stats,
            "market": {
                name: {"close": info.ltp, "chg_pct": info.chg_pct, "prev_close": info.prev_close}
                for name, info in store.prices.items()
            } if is_today else {},
            "india_vix": store.india_vix if is_today else None,
            "premarket_bias": store.premarket_bias if is_today else {},
            "news_pulse": {
                "sentiment": news.get("overall_sentiment"),
                "score": news.get("sentiment_score"),
                "summary": news.get("summary_for_trader"),
                "key_events": news.get("key_events", []),
                "risk_flags": news.get("risk_flags", []),
            } if news else {},
            "trades": [
                {k: t.get(k) for k in (
                    "id", "instrument", "action", "strike", "entry_time", "entry_price",
                    "exit_time", "exit_price", "exit_reason", "quantity", "pnl_final",
                    "confidence", "entry_reason", "fees_total")}
                for t in trades
            ],
            "ai": {},
        }

        ai_json = await self._ai_review(date, mode, stats, trades, news, known, store, is_today)
        if ai_json:
            report["ai"] = ai_json
            await self._persist_learnings(db, date, ai_json)
        else:
            report["ai"] = {"note": "AI review unavailable — stats-only report saved."}

        await db.save_daily_report(date, mode, report)
        print(f"[reporter] Daily report saved for {date} "
              f"({stats['n_trades']} trades, P&L ₹{stats['realized_pnl']:,.0f})")

        if notify_fn:
            try:
                grade = (ai_json or {}).get("self_grade", "—")
                await notify_fn(
                    f"📋 MAP TRADE Daily Report [{date}]\n"
                    f"Trades: {stats['n_trades']} | WR: {stats['win_rate']:.0f}% | "
                    f"P&L: ₹{stats['realized_pnl']:,.0f}\n"
                    f"Grade: {grade}"
                )
            except Exception as e:
                print(f"[reporter] notify error: {e}")

        return report

    async def _ai_review(self, date, mode, stats, trades, news, known, store, is_today) -> dict:
        news_block = "No news analysis was run today."
        if news:
            news_block = (
                f"Sentiment: {news.get('overall_sentiment')} ({news.get('sentiment_score', 0):+d})\n"
                f"Summary: {news.get('summary_for_trader', '')}\n"
                f"Risk flags: {', '.join(news.get('risk_flags', []) or ['none'])}"
            )

        known_lessons = "\n".join(
            f"- [{k.get('category')}] {k.get('lesson')}" for k in known[:25]
        ) or "None yet — this is early days."

        premarket = store.premarket_bias if is_today else {}
        premarket_block = (
            f"Bias: {premarket.get('bias', 'N/A')} (strength {premarket.get('bias_strength', '—')}) | "
            f"Risk: {premarket.get('risk_level', 'N/A')} | Stance: {premarket.get('recommended_stance', 'N/A')}\n"
            f"Reasoning: {premarket.get('reasoning', 'No premarket analysis ran.')}"
        )

        user_msg = DAILY_REPORT_USER.format(
            date=date, mode=mode.upper(), time=_now_ist().strftime("%H:%M"),
            premarket_block=premarket_block,
            news_block=news_block,
            market_block=_fmt_market_block(store) if is_today else "Historical date — market block omitted.",
            n_trades=stats["n_trades"], n_open=stats["n_open"],
            trades_block=_fmt_trades_block(trades),
            realized_pnl=stats["realized_pnl"], wins=stats["wins"], losses=stats["losses"],
            win_rate=stats["win_rate"], fees=stats["fees"],
            capital=store.current_capital if is_today else 0,
            known_lessons=known_lessons,
        )

        raw = await self.agent._ask(DAILY_REPORT_SYSTEM, user_msg)
        if not raw:
            return {}
        try:
            from ai.agent import _extract_json
            return _extract_json(raw)
        except Exception as e:
            print(f"[reporter] AI review parse error: {e} | raw: {raw[:200]}")
            return {"day_summary": raw[:400]}

    async def _persist_learnings(self, db, date: str, ai_json: dict) -> None:
        """Fan the AI review out into knowledge_base / ai_strategies / ai_suggestions."""
        knowledge = (ai_json.get("knowledge_gained") or [])[:MAX_KNOWLEDGE]
        # Per-trade lessons also become knowledge entries
        for pm in ai_json.get("trade_postmortems") or []:
            lesson = (pm.get("lesson") or "").strip()
            if lesson:
                knowledge.append({
                    "category": "MISTAKE" if pm.get("result") == "LOSS" else "STRATEGY_INSIGHT",
                    "lesson": lesson,
                    "confidence": 6,
                })
        if knowledge:
            await db.add_knowledge_entries(date, knowledge, source="daily_report")

        for strat in (ai_json.get("new_strategies") or [])[:MAX_STRATEGIES_PER_DAY]:
            if strat.get("name"):
                strat["created_date"] = date
                strat["status"] = "PROPOSED"
                await db.upsert_ai_strategy(strat)
                print(f"[reporter] New AI strategy proposed: {strat['name']}")

        suggestions = (ai_json.get("feature_requests") or [])[:MAX_SUGGESTIONS]
        if suggestions:
            await db.add_ai_suggestions(date, suggestions)
