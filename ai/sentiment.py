"""Lightweight lexicon sentiment for market headlines.

Zero extra deps. Not as good as FinBERT but instant, offline, deterministic —
good enough as a pre-filter before the LLM sees them.
"""
from __future__ import annotations

import re
from collections import Counter

POSITIVE = {
    "surge", "rally", "gain", "jump", "soar", "beat", "beats", "upgrade", "bullish",
    "record", "high", "profit", "growth", "outperform", "strong", "expand", "boost",
    "buy", "accumulate", "positive", "optimistic", "recovery", "rebound", "breakout",
}
NEGATIVE = {
    "fall", "drop", "slump", "plunge", "crash", "miss", "misses", "downgrade", "bearish",
    "low", "loss", "decline", "underperform", "weak", "cut", "slash", "warning",
    "sell", "reduce", "negative", "concern", "recession", "breakdown", "probe", "fraud",
    "layoff", "layoffs", "default", "downturn",
}
INTENSIFIERS = {"sharply", "massively", "record", "sudden"}

_WORD = re.compile(r"[a-zA-Z]+")


def score_text(text: str) -> int:
    """Return score in [-10, 10]. Positive = bullish."""
    if not text:
        return 0
    words = [w.lower() for w in _WORD.findall(text)]
    if not words:
        return 0
    pos = sum(1 for w in words if w in POSITIVE)
    neg = sum(1 for w in words if w in NEGATIVE)
    mult = 2 if any(w in INTENSIFIERS for w in words) else 1
    raw = (pos - neg) * mult
    return max(-10, min(10, raw))


def label(score: int) -> str:
    if score >= 3:
        return "BULLISH"
    if score <= -3:
        return "BEARISH"
    return "NEUTRAL"


def score_headlines(headlines: list[dict]) -> dict:
    """headlines: [{'headline': str, 'source': str, ...}] → aggregate report."""
    if not headlines:
        return {"score": 0, "label": "NEUTRAL", "counts": {}, "top_positive": [], "top_negative": []}
    scored = []
    for h in headlines:
        s = score_text(h.get("headline", ""))
        scored.append({**h, "score": s})
    avg = round(sum(x["score"] for x in scored) / len(scored) * 2)
    avg = max(-10, min(10, avg))
    counts = Counter(label(x["score"]) for x in scored)
    top_pos = sorted(scored, key=lambda x: -x["score"])[:3]
    top_neg = sorted(scored, key=lambda x: x["score"])[:3]
    return {
        "score": avg,
        "label": label(avg),
        "counts": dict(counts),
        "top_positive": [{"headline": x["headline"], "score": x["score"]} for x in top_pos if x["score"] > 0],
        "top_negative": [{"headline": x["headline"], "score": x["score"]} for x in top_neg if x["score"] < 0],
        "total": len(scored),
    }


def score_symbol_headlines(symbol: str, headlines: list[dict]) -> dict:
    """Filter headlines mentioning the symbol, then score."""
    sym = symbol.upper().replace(".NS", "").replace(".BO", "")
    matched = [h for h in headlines if sym in h.get("headline", "").upper()]
    result = score_headlines(matched)
    result["symbol"] = symbol
    result["matched"] = len(matched)
    return result
