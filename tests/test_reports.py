"""Tests for the AI learning system: daily reporter, news brain, DB helper logic."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai.news import NewsBrain, _clean, _parse_rss
from ai.reporter import DailyReporter, _fmt_trades_block, _stats
from data.database import _qmark_to_pg


# ── database helpers ──────────────────────────────────────────────────────────

class TestQmarkToPg:
    def test_converts_placeholders_in_order(self):
        assert _qmark_to_pg("INSERT INTO t VALUES (?,?,?)") == "INSERT INTO t VALUES ($1,$2,$3)"

    def test_no_placeholders_untouched(self):
        assert _qmark_to_pg("SELECT * FROM t") == "SELECT * FROM t"


# ── news parsing ──────────────────────────────────────────────────────────────

_SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>Nifty surges 300 points as RBI holds repo rate steady</title>
    <link>https://example.com/1</link></item>
  <item><title>short</title><link>https://example.com/2</link></item>
  <item><title>Bank Nifty hits record high on strong &amp;lt;b&amp;gt;FII inflows</title>
    <link>https://example.com/3</link></item>
</channel></rss>"""


class TestNewsParsing:
    def test_parse_rss_extracts_items(self):
        items = _parse_rss(_SAMPLE_RSS, "TestFeed", max_items=10)
        assert len(items) == 2  # "short" title is skipped
        assert items[0]["source"] == "TestFeed"
        assert "Nifty surges" in items[0]["headline"]
        assert items[0]["url"] == "https://example.com/1"

    def test_parse_rss_malformed_returns_empty(self):
        assert _parse_rss("<not-xml", "X", 5) == []

    def test_clean_strips_html(self):
        assert _clean("<b>Nifty</b> &amp; Sensex") == "Nifty & Sensex"


_NEWS_AI_JSON = json.dumps({
    "overall_sentiment": "BULLISH",
    "sentiment_score": 6,
    "expected_impact": {"NIFTY": "up"},
    "key_events": [{"event": "RBI holds rates", "why_it_matters": "supportive", "sentiment": "POS"}],
    "risk_flags": ["US CPI tonight"],
    "summary_for_trader": "Positive open expected.",
    "lessons": [{"category": "NEWS_PATTERN", "lesson": "Rate holds are mildly bullish", "confidence": 7}],
})


@pytest.mark.asyncio
async def test_news_brain_scan_persists_and_updates_store():
    agent = MagicMock()
    agent._ask = AsyncMock(return_value=_NEWS_AI_JSON)
    brain = NewsBrain(agent)

    headlines = [{"source": "ET", "headline": "Nifty surges on RBI rate hold decision", "url": "u"}]
    with patch("ai.news.fetch_headlines", AsyncMock(return_value=headlines)), \
         patch("data.database.save_news_items", AsyncMock()) as save_items, \
         patch("data.database.save_news_analysis", AsyncMock()) as save_an, \
         patch("data.database.add_knowledge_entries", AsyncMock()) as add_kn:
        analysis = await brain.scan()

    assert analysis["overall_sentiment"] == "BULLISH"
    save_items.assert_awaited_once()
    save_an.assert_awaited_once()
    add_kn.assert_awaited_once()

    from data.store import store
    assert store.news_insight["sentiment"] == "BULLISH"
    assert store.news_insight["score"] == 6
    assert brain.last_status == "ok"


@pytest.mark.asyncio
async def test_news_brain_scan_no_headlines_returns_empty():
    brain = NewsBrain(MagicMock())
    with patch("ai.news.fetch_headlines", AsyncMock(return_value=[])):
        assert await brain.scan() == {}
    # Distinct status so the route can say "feeds unreachable" not "AI failed".
    assert brain.last_status == "no_headlines"
    assert brain.last_headline_count == 0


@pytest.mark.asyncio
async def test_news_brain_scan_ai_failure_still_saves_headlines():
    agent = MagicMock()
    agent._ask = AsyncMock(return_value="")  # AI unreachable
    brain = NewsBrain(agent)
    headlines = [{"source": "ET", "headline": "Some market headline for today", "url": "u"}]
    with patch("ai.news.fetch_headlines", AsyncMock(return_value=headlines)), \
         patch("data.database.save_news_items", AsyncMock()) as save_items, \
         patch("data.database.save_news_analysis", AsyncMock()) as save_an:
        assert await brain.scan() == {}
    save_items.assert_awaited_once()
    save_an.assert_not_awaited()
    # Headlines reached us but AI produced nothing — distinct from no_headlines.
    assert brain.last_status == "analysis_failed"
    assert brain.last_headline_count == 1


# ── reporter stats/formatting ─────────────────────────────────────────────────

def _trade(pnl=100.0, closed=True, **kw):
    t = {
        "id": 1, "instrument": "NIFTY", "action": "BUY_CE", "strike": 24200,
        "entry_time": "2026-07-10T09:45:00", "entry_price": 120.0, "quantity": 65,
        "confidence": 8, "entry_reason": "BOS + pullback", "fees_total": 45.0,
    }
    if closed:
        t.update({"exit_time": "2026-07-10T11:00:00", "exit_price": 130.0,
                  "exit_reason": "TARGET", "pnl_final": pnl})
    else:
        t.update({"exit_time": None, "exit_price": None, "exit_reason": None, "pnl_final": None})
    t.update(kw)
    return t


class TestReporterStats:
    def test_stats_mixed(self):
        s = _stats([_trade(500), _trade(-300), _trade(closed=False)])
        assert s["n_trades"] == 3
        assert s["n_open"] == 1
        assert s["wins"] == 1 and s["losses"] == 1
        assert s["win_rate"] == 50.0
        assert s["realized_pnl"] == 200
        assert s["fees"] == 90.0

    def test_stats_empty(self):
        s = _stats([])
        assert s["n_trades"] == 0 and s["win_rate"] == 0.0

    def test_trades_block_mentions_outcome(self):
        block = _fmt_trades_block([_trade(500), _trade(closed=False)])
        assert "[WIN]" in block and "[OPEN]" in block
        assert "BOS + pullback" in block

    def test_trades_block_empty(self):
        assert "No trades" in _fmt_trades_block([])


# ── reporter end-to-end (AI mocked) ──────────────────────────────────────────

_REPORT_AI_JSON = json.dumps({
    "day_summary": "Choppy day, one good trend trade.",
    "market_story": "Market rallied on RBI hold.",
    "prediction_accuracy": "Premarket bias matched.",
    "trade_postmortems": [{
        "trade_ref": "NIFTY 24200 CE 09:45", "result": "PROFIT", "pnl": 500,
        "why": "Entered on BOS with trend", "what_went_right": "Followed structure",
        "what_went_wrong": None, "lesson": "BOS entries in trend work",
    }],
    "no_trade_reason": None,
    "knowledge_gained": [{"category": "MARKET_BEHAVIOUR", "lesson": "Trend days follow RBI holds", "confidence": 7}],
    "new_strategies": [{"name": "RBI-Day Trend Rider", "rationale": "Pattern on policy days",
                        "rules": ["Enter after 10:00 BOS"], "when_to_use": "Policy days"}],
    "feature_requests": [{"category": "DATA", "suggestion": "Give me FII/DII flow data",
                          "priority": "HIGH", "why": "Flows drive trends"}],
    "tomorrow_plan": "Watch gap.",
    "self_grade": "B — solid but late entry",
})


@pytest.mark.asyncio
async def test_reporter_generate_persists_everything():
    agent = MagicMock()
    agent._ask = AsyncMock(return_value=_REPORT_AI_JSON)
    reporter = DailyReporter(agent)

    with patch("data.database.get_today_trades", AsyncMock(return_value=[_trade(500)])), \
         patch("data.database.get_news_analysis", AsyncMock(return_value={"overall_sentiment": "BULLISH", "sentiment_score": 6})), \
         patch("data.database.get_knowledge", AsyncMock(return_value=[])), \
         patch("data.database.save_daily_report", AsyncMock()) as save_rep, \
         patch("data.database.add_knowledge_entries", AsyncMock()) as add_kn, \
         patch("data.database.upsert_ai_strategy", AsyncMock()) as up_strat, \
         patch("data.database.add_ai_suggestions", AsyncMock()) as add_sug:
        report = await reporter.generate()

    assert report["ai"]["day_summary"].startswith("Choppy")
    assert report["stats"]["n_trades"] == 1

    save_rep.assert_awaited_once()
    saved_date, saved_mode, saved_report = save_rep.await_args.args
    assert saved_report["ai"]["self_grade"].startswith("B")

    # postmortem lesson is folded into knowledge alongside knowledge_gained
    add_kn.assert_awaited_once()
    entries = add_kn.await_args.args[1]
    lessons = [e["lesson"] for e in entries]
    assert "Trend days follow RBI holds" in lessons
    assert "BOS entries in trend work" in lessons

    up_strat.assert_awaited_once()
    assert up_strat.await_args.args[0]["name"] == "RBI-Day Trend Rider"
    assert up_strat.await_args.args[0]["status"] == "PROPOSED"

    add_sug.assert_awaited_once()
    assert add_sug.await_args.args[1][0]["priority"] == "HIGH"


@pytest.mark.asyncio
async def test_reporter_ai_unavailable_saves_stats_only():
    agent = MagicMock()
    agent._ask = AsyncMock(return_value="")
    reporter = DailyReporter(agent)

    with patch("data.database.get_today_trades", AsyncMock(return_value=[])), \
         patch("data.database.get_news_analysis", AsyncMock(return_value=None)), \
         patch("data.database.get_knowledge", AsyncMock(return_value=[])), \
         patch("data.database.save_daily_report", AsyncMock()) as save_rep:
        report = await reporter.generate()

    save_rep.assert_awaited_once()
    assert "note" in report["ai"]
    assert report["stats"]["n_trades"] == 0
