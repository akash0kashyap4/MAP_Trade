from __future__ import annotations
import numpy as np
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


async def run_nightly_review(agent, db_get_trades, db_save_rules, trading_cfg: dict, notify_fn=None):
    try:
        trades = await db_get_trades(days=30, completed_only=True)
        if len(trades) < 10:
            print("[learner] Not enough trades for nightly review (need 10+).")
            return

        rules  = await agent.nightly_review(trades)
        stats  = _calculate_stats(trades)

        await db_save_rules(rules, stats)

        apply_rules_to_config(rules, trading_cfg)

        msg = (
            f"🧠 Ragi Nightly Learn\n"
            f"WR={stats['win_rate']:.1f}%  PnL=₹{stats['total_pnl']:,.0f}\n"
            f"Insight: {rules.get('key_insight', 'N/A')}"
        )
        if notify_fn:
            await notify_fn(msg)
        print(f"[learner] {msg}")
    except Exception as e:
        import traceback
        print(f"[learner] Nightly review failed: {e}\n{traceback.format_exc()}")
        if notify_fn:
            try:
                await notify_fn(f"⚠️ Nightly learning review failed:\nError: {e}")
            except Exception:
                pass


async def weekly_review(agent, db_get_trades, notify_fn=None):
    try:
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
    except Exception as e:
        import traceback
        print(f"[learner] Weekly review failed: {e}\n{traceback.format_exc()}")
        if notify_fn:
            try:
                await notify_fn(f"⚠️ Weekly review failed:\nError: {e}")
            except Exception:
                pass


def apply_rules_to_config(rules: dict, trading_cfg: dict) -> list[str]:
    """Merge learner-suggested rules into the live TRADING config.

    Kept intentionally narrow — it only updates parameters where a bad AI value
    can't disable trading (e.g. confidence threshold is clamped to 1..9 so the
    bot cannot lock itself out). Called both by the nightly review and at
    process start (see main.py) so a fresh boot instantly benefits from what
    the bot learned yesterday instead of starting from stock defaults."""
    if not isinstance(rules, dict) or not rules:
        return []
    applied: list[str] = []

    # Confidence threshold — clamp to 1..9 so we never block ALL trades.
    threshold = rules.get("updated_confidence_threshold")
    if isinstance(threshold, (int, float)):
        t = max(1, min(9, int(threshold)))
        if trading_cfg.get("min_confidence") != t:
            trading_cfg["min_confidence"] = t
            applied.append(f"min_confidence={t}")

    # VIX / IV thresholds — informational only (prompt reads them). Persist so
    # the AI prompt sees the learned value on next tick.
    for k_src, k_dst in (("vix_threshold_suggested", "vix_threshold"),
                         ("iv_threshold_suggested", "iv_threshold")):
        v = rules.get(k_src)
        if isinstance(v, (int, float)) and 5 <= v <= 60:
            if trading_cfg.get(k_dst) != float(v):
                trading_cfg[k_dst] = float(v)
                applied.append(f"{k_dst}={v}")

    # Free-form param overrides the AI wrote in `rule_changes`, whitelisted so
    # a hallucinated `max_positions=0` can't brick the bot.
    _WHITELIST = {
        "trailing_sl_trigger", "trailing_sl_step",
        "fallback_sl_pct", "fallback_target_pct",
        "partial_book_ratio",
    }
    changes = rules.get("rule_changes") or {}
    if isinstance(changes, dict):
        for k, v in changes.items():
            if k in _WHITELIST and isinstance(v, (int, float)):
                if trading_cfg.get(k) != v:
                    trading_cfg[k] = v
                    applied.append(f"{k}={v}")

    if applied:
        print(f"[learner] Applied to TRADING: {', '.join(applied)}")
    return applied


async def load_persisted_rules(db_get_latest_rules, trading_cfg: dict) -> list[str]:
    """Startup hook — load the most recent learning_rules row from DB and merge."""
    try:
        rules = await db_get_latest_rules()
    except Exception as e:
        print(f"[learner] Could not load persisted rules: {e}")
        return []
    return apply_rules_to_config(rules or {}, trading_cfg)


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
        )

    async def weekly_review(self, notify_fn=None):
        await weekly_review(self._agent, self._db.get_trades, notify_fn)
