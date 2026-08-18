# AI Brain Build Plan — Best & Free Stack

Goal: MAP_Trade ke liye ek AI "brain" build karna jo trading decisions, research, sentiment aur backtesting kar sake — bina paid subscription ke, sirf free / open-source tools se.

Repo me pehle se `ai/agent.py` Claude Code CLI (`claude -p`) use karta hai — is plan ka base wahi hai.

---

## 1. Architecture (Layers)

```
                +-------------------------+
                |  Scheduler / main.py    |
                +-----------+-------------+
                            |
        +-------------------+-------------------+
        |                                       |
+-------v--------+                     +--------v---------+
|  Data Layer    |                     |  Decision Layer  |
| - AngelOne     |                     | - ai/agent.py    |
| - Groww        |                     | - Claude/Groq    |
| - News feeds   |                     | - Rule filters   |
+-------+--------+                     +--------+---------+
        |                                       |
+-------v--------+                     +--------v---------+
| Feature Layer  |                     | Execution Layer  |
| - indicators/  |                     | - bot/           |
| - sentiment    |                     | - paper first    |
+----------------+                     +------------------+
                            |
                +-----------v-------------+
                |  Learner / Reporter     |
                |  ai/learner.py          |
                +-------------------------+
```

---

## 2. Free LLM Options (ranked)

| Provider | Free tier | Best for | Notes |
|---|---|---|---|
| Claude Code CLI (`claude -p`) | Uses your existing session, no API key | Primary brain — already wired in `ai/claude_runtime.py` | Keep as default |
| Groq (Llama 3.1 / 3.3, Mixtral) | Generous free API | Fast fallback, cheap batching | Add as secondary provider |
| Google Gemini 1.5 Flash | 15 RPM free | Sentiment / news summarization | Good multimodal |
| Ollama (local) | 100% free, offline | Backtest labelling, no rate limits | Needs GPU/CPU RAM |
| OpenRouter free models | Rotating free models | Redundancy | Rate-limited |

Wire order (fallback chain): `Claude → Groq → Gemini → Ollama local`.

## 3. Free Data Sources

- Prices: AngelOne + Groww (already integrated)
- News: RSS (Moneycontrol, Livemint, Economic Times, Reuters), NSE announcements RSS
- Fundamentals: Screener.in (scrape), Yahoo Finance (`yfinance`)
- Macro: FRED API (free key), RBI data portal
- Sentiment: Reddit (`/r/IndianStreetBets`), StockTwits public API
- Options chain: NSE public JSON endpoints

## 4. Free Libraries

- `pandas`, `numpy`, `pandas-ta` — indicators
- `backtrader` / existing `backtest/` — strategy testing
- `vectorbt` (free) — fast vectorized backtests
- `feedparser` — RSS ingestion
- `transformers` + `finbert` — offline sentiment scoring
- `duckdb` — local analytics on trade history

## 5. Milestones

### M1 — Provider registry hardening (1 day)
- Extend `ai/provider_registry.py` with Groq + Gemini adapters
- Env-driven fallback chain, timeout + retry
- Unit tests for each provider mock

### M2 — News + Sentiment pipeline (2 days)
- `ai/news.py` → add RSS ingesters + dedupe
- New `ai/sentiment.py` using FinBERT locally (Ollama optional)
- Store scored headlines in SQLite (`data/`) for the decision prompt

### M3 — Decision brain upgrade (2 days)
- Enrich `DECISION_USER` prompt with: sentiment score, sector strength, options OI shift
- Add self-critique step: second LLM call reviews first call's JSON
- Hard rule filter after LLM (max risk, blacklist, circuit)

### M4 — Learner loop (2 days)
- `ai/learner.py` → nightly job:
  - Pull today's trades + outcomes
  - Ask LLM to tag failure modes
  - Append to `data/lessons.jsonl`
  - Next day's prompt injects top-N lessons

### M5 — Backtest harness (2 days)
- Replay historical candles through the exact same `ai/agent.py` path
- Cache LLM responses on `(symbol, timestamp, prompt_hash)` to keep re-runs free
- Metrics: win rate, expectancy, max DD, Sharpe

### M6 — Paper trade for 2 weeks
- No real capital until M5 metrics beat baseline (buy-and-hold NIFTY)

## 6. Guardrails (non-negotiable)

- Paper trading gate before any live order (env flag `LIVE_TRADING=false` default)
- Per-day loss cap, per-trade risk cap in `config/`
- Every LLM decision logged with prompt + response hash for audit
- Kill switch: single file `HALT` in repo root stops all orders

## 7. Cost estimate

- LLM: ₹0 (Claude Code session + Groq/Gemini free tiers + local Ollama)
- Data: ₹0 (broker feeds already paid via account; news RSS free)
- Hosting: existing Vercel + local runner
- Only cost = compute if Ollama runs on cloud GPU (skip unless needed)

## 8. Red flags to avoid

- "Guaranteed profit" bots — scam
- Closed-source signal Telegram groups
- Any tool asking for broker password (only API keys via official portals)
- Over-fitting to 2023–2025 bull run — always test on 2018 and 2020 crashes

## 9. Next actions

1. Confirm asset class scope (equity intraday? F&O? crypto?) — plan currently assumes NSE equity + index F&O
2. Implement M1 provider registry expansion
3. Turn on paper trading mode end-to-end, then iterate M2–M6
