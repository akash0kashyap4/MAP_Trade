from __future__ import annotations
import numpy as np
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


async def run_nightly_review(agent, db_get_trades, db_save_rules, trading_cfg: dict, notify_fn=None,
                            db_save_ai_request=None):
    trades = await db_get_trades(days=30, completed_only=True)
    if len(trades) < 5:
        print(f"[learner] Not enough trades for nightly review (have {len(trades)}, need 5+).")
        return

    rules  = await agent.nightly_review(trades)
    stats  = _calculate_stats(trades)

    await db_save_rules(rules, stats)

    # Save any new feature requests Claude generated
    if db_save_ai_request:
        for req in rules.get("feature_requests") or []:
            if req.get("title"):
                await db_save_ai_request(
                    title=req["title"],
                    description=req.get("description", ""),
                    priority=req.get("priority", "MEDIUM"),
                    feature_key=req.get("feature_key"),
                )

    # Push freshly learned rules back into the agent immediately
    agent.update_learned_rules(rules)

    threshold = rules.get("updated_confidence_threshold")
    if isinstance(threshold, int) and 6 <= threshold <= 9:
        trading_cfg["min_confidence"] = threshold
        print(f"[learner] Confidence threshold updated to {threshold}")

    msg = (
        f"🧠 Ragi Nightly Learn\n"
        f"WR={stats['win_rate']:.1f}%  PnL=₹{stats['total_pnl']:,.0f}\n"
        f"Insight: {rules.get('key_insight', 'N/A')}"
    )
    if notify_fn:
        await notify_fn(msg)
    print(f"[learner] {msg}")


async def weekly_review(agent, db_get_trades, notify_fn=None):
    trades = await db_get_trades(days=90, completed_only=True)
    if len(trades) < 20:
        print("[learner] Not enough trades for weekly review.")
        return

    stats = _calculate_stats(trades)
    rules = await agent.nightly_review(trades)

    msg = (
        f"📊 Ragi Weekly Review (90 days)\n"
        f"Trades={stats['total']}  WR={stats['win_rate']:.1f}%\n"
        f"PnL=₹{stats['total_pnl']:,.0f}  Sharpe={stats['sharpe']:.2f}\n"
        f"Key: {rules.get('key_insight', 'N/A')}"
    )
    if notify_fn:
        await notify_fn(msg)
    print(f"[learner] {msg}")


def _calculate_stats(trades: list) -> dict:
    pnls  = [t.get("pnl_final", 0) for t in trades]
    wins  = [p for p in pnls if p > 0]
    total = len(pnls)

    arr = np.array(pnls)
    sharpe = float(arr.mean() / arr.std() * np.sqrt(252)) if arr.std() > 0 else 0.0

    return {
        "total":      total,
        "wins":       len(wins),
        "losses":     total - len(wins),
        "win_rate":   len(wins) / total * 100 if total else 0.0,
        "total_pnl":  sum(pnls),
        "avg_pnl":    sum(pnls) / total if total else 0.0,
        "sharpe":     round(sharpe, 2),
    }


class Learner:
    def __init__(self, agent, db):
        self._agent = agent
        self._db    = db
        from config import TRADING
        self._trading_cfg = TRADING

    async def run_nightly_review(self, notify_fn=None):
        await run_nightly_review(
            self._agent,
            self._db.get_trades,
            self._db.save_learning_rules,
            self._trading_cfg,
            notify_fn,
            db_save_ai_request=getattr(self._db, "save_ai_request", None),
        )

    async def weekly_review(self, notify_fn=None):
        await weekly_review(self._agent, self._db.get_trades, notify_fn)
