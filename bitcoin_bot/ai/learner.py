"""
Nightly Learning Module
Analyzes trades and suggests improvements
"""

import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class Learner:
    """Analyze trades and suggest rule improvements"""

    def __init__(self, ai_agent):
        self.ai_agent = ai_agent

    async def analyze_trades(self, trades: List[Dict]) -> Dict:
        """Analyze trading performance"""
        if not trades:
            return {}

        total = len(trades)
        winners = [t for t in trades if t.get("pnl", 0) > 0]
        losers = [t for t in trades if t.get("pnl", 0) < 0]

        total_pnl = sum(t.get("pnl", 0) for t in trades)
        avg_win = sum(t.get("pnl", 0) for t in winners) / len(winners) if winners else 0
        avg_loss = sum(t.get("pnl", 0) for t in losers) / len(losers) if losers else 0

        stats = {
            "total_trades": total,
            "wins": len(winners),
            "losses": len(losers),
            "win_rate": len(winners) / total * 100 if total > 0 else 0,
            "avg_win": avg_win,
            "avg_loss": abs(avg_loss) if avg_loss else 0,
            "profit_factor": avg_win / abs(avg_loss) if avg_loss != 0 else 0,
            "total_pnl": total_pnl,
        }

        return stats

    async def get_suggestions(self, trades: List[Dict], stats: Dict) -> List[str]:
        """Get improvement suggestions from Claude"""
        try:
            suggestions = await self.ai_agent.learn_from_trades(trades)
            return suggestions
        except Exception as e:
            logger.error(f"Get suggestions error: {e}")
            return []
