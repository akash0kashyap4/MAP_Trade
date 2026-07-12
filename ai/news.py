"""
Ragi News Brain — fetches Indian market news from free RSS feeds (no API key),
asks Claude to convert headlines into a trading-relevant "market pulse", stores
both, and feeds the pulse into premarket + intraday decision prompts.

Every scan also extracts general NEWS_PATTERN lessons into the knowledge base,
so the bot gradually learns how news maps to market behaviour.
"""
from __future__ import annotations

import asyncio
import html
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime

import aiohttp
import pytz

from ai.prompts import NEWS_ANALYSIS_SYSTEM, NEWS_ANALYSIS_USER

IST = pytz.timezone("Asia/Kolkata")

# Free RSS feeds — no API key required. Add/remove sources here.
RSS_FEEDS: list[tuple[str, str]] = [
    ("EconomicTimes", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("Moneycontrol", "https://www.moneycontrol.com/rss/marketreports.xml"),
    ("LiveMint", "https://www.livemint.com/rss/markets"),
    ("GoogleNews",
     "https://news.google.com/rss/search?q=nifty+OR+sensex+OR+%22bank+nifty%22+OR+RBI+OR+FII"
     "&hl=en-IN&gl=IN&ceid=IN:en"),
]

_TAG_RE = re.compile(r"<[^>]+>")


def _now_ist() -> datetime:
    return datetime.now(IST)


def _clean(text: str) -> str:
    return html.unescape(_TAG_RE.sub("", text or "")).strip()


def _parse_rss(xml_text: str, source: str, max_items: int) -> list[dict]:
    """Parse RSS 2.0 <item> entries; tolerate malformed feeds."""
    items: list[dict] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items
    for item in root.iter("item"):
        title = _clean(item.findtext("title") or "")
        if not title or len(title) < 15:
            continue
        items.append({
            "source": source,
            "headline": title,
            "url": (item.findtext("link") or "").strip(),
        })
        if len(items) >= max_items:
            break
    return items


async def fetch_headlines(max_per_feed: int = 10, timeout_s: int = 12) -> list[dict]:
    """Fetch and dedupe headlines across all feeds. Never raises."""
    async def _one(session: aiohttp.ClientSession, source: str, url: str) -> list[dict]:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout_s)) as resp:
                if resp.status != 200:
                    return []
                return _parse_rss(await resp.text(errors="replace"), source, max_per_feed)
        except Exception as e:
            print(f"[news] feed error {source}: {e}")
            return []

    headers = {"User-Agent": "Mozilla/5.0 (RagiBot news reader)"}
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            results = await asyncio.gather(*(_one(session, s, u) for s, u in RSS_FEEDS))
    except Exception as e:
        print(f"[news] session error: {e}")
        return []

    seen: set[str] = set()
    merged: list[dict] = []
    for feed_items in results:
        for it in feed_items:
            key = re.sub(r"\W+", "", it["headline"].lower())[:80]
            if key and key not in seen:
                seen.add(key)
                merged.append(it)
    return merged[:35]


class NewsBrain:
    """Fetch → analyze → persist → expose today's news pulse to the trading brain."""

    def __init__(self, agent):
        self.agent = agent  # TradingAgent — reuses its Claude plumbing
        # Last scan outcome, so callers (the /news/scan route) can surface a
        # specific, actionable reason instead of one vague "scan failed".
        # One of: "idle" | "ok" | "no_headlines" | "analysis_failed"
        self.last_status: str = "idle"
        self.last_headline_count: int = 0

    async def scan(self, notify_fn=None) -> dict:
        """Full news scan. Safe to call multiple times a day (upserts)."""
        from data import database as db
        from data.store import store

        today = _now_ist().strftime("%Y-%m-%d")
        headlines = await fetch_headlines()
        self.last_headline_count = len(headlines)
        if not headlines:
            self.last_status = "no_headlines"
            print("[news] No headlines fetched — skipping analysis")
            return {}
        print(f"[news] Fetched {len(headlines)} headlines")

        analysis = await self._analyze(headlines)
        if not analysis:
            # Headlines reached us but the AI step produced nothing — persist the
            # raw headlines so the UI still has something to show.
            self.last_status = "analysis_failed"
            await db.save_news_items(today, headlines)
            return {}

        self.last_status = "ok"
        # Tag each stored headline with sentiment where the AI mentioned it
        await db.save_news_items(today, headlines)
        await db.save_news_analysis(today, analysis)

        lessons = analysis.get("lessons") or []
        if lessons:
            await db.add_knowledge_entries(today, lessons, source="news_scan")

        store.news_insight = {
            "updated": _now_ist().strftime("%H:%M"),
            "sentiment": analysis.get("overall_sentiment", "NEUTRAL"),
            "score": analysis.get("sentiment_score", 0),
            "summary": analysis.get("summary_for_trader", ""),
            "risk_flags": analysis.get("risk_flags", []),
            "headline_count": len(headlines),
        }

        if notify_fn:
            try:
                await notify_fn(
                    f"📰 Ragi News Pulse [{store.news_insight['updated']}]\n"
                    f"Sentiment: {store.news_insight['sentiment']} "
                    f"({store.news_insight['score']:+d})\n"
                    f"{store.news_insight['summary']}"
                )
            except Exception as e:
                print(f"[news] notify error: {e}")

        print(f"[news] Pulse: {store.news_insight['sentiment']} ({store.news_insight['score']:+d})")
        return analysis

    async def _analyze(self, headlines: list[dict]) -> dict:
        now = _now_ist()
        block = "\n".join(f"- [{h['source']}] {h['headline']}" for h in headlines)
        user_msg = NEWS_ANALYSIS_USER.format(
            date=now.strftime("%Y-%m-%d"), time=now.strftime("%H:%M"), headlines_block=block,
        )
        raw = await self.agent._ask(NEWS_ANALYSIS_SYSTEM, user_msg)
        if not raw:
            return {}
        try:
            from ai.agent import _extract_json
            analysis = _extract_json(raw)
        except Exception as e:
            print(f"[news] analysis parse error: {e} | raw: {raw[:200]}")
            return {}
        try:
            analysis["sentiment_score"] = max(-10, min(10, int(analysis.get("sentiment_score", 0))))
        except Exception:
            analysis["sentiment_score"] = 0
        return analysis
