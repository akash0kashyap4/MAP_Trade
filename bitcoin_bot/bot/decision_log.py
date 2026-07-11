"""
Decision Logging
Structured logging of all trading decisions and their outcomes
"""

import logging
import json
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class DecisionLog:
    """Log trading decisions for audit trail and learning"""

    def __init__(self, db=None):
        self.db = db
        self.decisions = []

    def log_decision(
        self,
        decision: Dict,
        market_data: Dict,
        guards: Dict,
        action_taken: str,
    ):
        """
        Log a trading decision with full context

        Args:
            decision: Claude's decision (action, confidence, etc)
            market_data: Current market data
            guards: Risk guard results (passed/blocked)
            action_taken: What actually happened (BUY/SELL/SKIP)
        """
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "claude_decision": decision,
            "market_snapshot": {
                "price": market_data.get("current_price"),
                "rsi": market_data.get("indicators", {}).get("rsi"),
                "ema_ratio": market_data.get("indicators", {}).get("ema9"),
            },
            "guards": guards,
            "action_taken": action_taken,
        }

        self.decisions.append(entry)

        if self.db:
            self._store_in_db(entry)

    def log_exit(
        self,
        trade_id: str,
        exit_price: float,
        reason: str,
        pnl: float,
    ):
        """Log position exit"""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "trade_id": trade_id,
            "exit_price": exit_price,
            "reason": reason,  # "sl_hit" / "target_hit" / "claude_exit" / "manual"
            "pnl": pnl,
        }

        if self.db:
            self._store_exit_in_db(entry)

        logger.info(f"Exit logged: {reason}, P&L: ${pnl:.2f}")

    def _store_in_db(self, entry: Dict):
        """Store decision in database"""
        try:
            # Implement DB storage if needed
            pass
        except Exception as e:
            logger.error(f"Decision log storage error: {e}")

    def _store_exit_in_db(self, entry: Dict):
        """Store exit in database"""
        try:
            # Implement DB storage if needed
            pass
        except Exception as e:
            logger.error(f"Exit log storage error: {e}")

    def get_decision_history(self, limit: int = 50) -> list:
        """Get recent decision history"""
        return self.decisions[-limit:]
