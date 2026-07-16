"""
Feature 2: Index breadth data — NIFTY vs BANKNIFTY vs SENSEX divergence
and advance-decline signal alongside index closes.
"""
from __future__ import annotations
from data.store import store


def calc_breadth() -> dict:
    """
    Compute cross-index divergence and a simple advance-decline breadth signal.
    Called every tick and injected into market context + SSE payload.
    """
    prices = store.prices
    nifty_pct  = prices["NIFTY"].chg_pct
    bank_pct   = prices["BANKNIFTY"].chg_pct
    sensex_pct = prices["SENSEX"].chg_pct

    # How many indices are advancing
    movers = [nifty_pct, bank_pct, sensex_pct]
    advancing = sum(1 for x in movers if x > 0.1)
    declining = sum(1 for x in movers if x < -0.1)

    # NIFTY vs BANKNIFTY divergence (positive = bank leading)
    nifty_bank_div = round(bank_pct - nifty_pct, 2)

    # Overall market tone
    avg_move = round(sum(movers) / 3, 2)
    if advancing >= 2 and avg_move > 0.2:
        tone = "BROAD_RALLY"
    elif declining >= 2 and avg_move < -0.2:
        tone = "BROAD_SELLOFF"
    elif abs(nifty_bank_div) > 0.5:
        tone = "DIVERGENT"   # indices moving differently — choppy signal
    else:
        tone = "MIXED"

    return {
        "nifty_chg_pct":    nifty_pct,
        "banknifty_chg_pct": bank_pct,
        "sensex_chg_pct":   sensex_pct,
        "nifty_bank_div":   nifty_bank_div,   # + = bank outperforming
        "advancing":        advancing,
        "declining":        declining,
        "avg_move_pct":     avg_move,
        "market_tone":      tone,
    }


def breadth_summary(breadth: dict) -> str:
    """One-line summary for Claude's prompt."""
    return (
        f"NIFTY {breadth['nifty_chg_pct']:+.2f}% | "
        f"BANKNIFTY {breadth['banknifty_chg_pct']:+.2f}% | "
        f"SENSEX {breadth['sensex_chg_pct']:+.2f}% | "
        f"Tone={breadth['market_tone']} | "
        f"BankVsNifty={breadth['nifty_bank_div']:+.2f}%"
    )
