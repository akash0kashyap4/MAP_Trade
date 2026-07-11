"""
Claude AI Agent for trading decisions
Subprocess wrapper around Claude Code CLI
"""

import json
import logging
import subprocess
from typing import Dict, List, Optional
from datetime import datetime

from .schema import DecisionSchema
from .prompts import get_trading_prompt

logger = logging.getLogger(__name__)


class AIAgent:
    """Wrapper around Claude Code CLI for trading decisions"""

    def __init__(self, model: str, claude_bin: str, timeout_sec: int = 10):
        self.model = model
        self.claude_bin = claude_bin
        self.timeout_sec = timeout_sec

    async def get_trading_decision(self, market_context: Dict) -> Optional[DecisionSchema]:
        """
        Query Claude for trading decision given market context

        Args:
            market_context: Dict with OHLCV, indicators, portfolio, etc

        Returns:
            DecisionSchema if valid, None if error
        """
        try:
            # Build prompt
            prompt = get_trading_prompt(market_context)

            # Call Claude via subprocess
            result = subprocess.run(
                [self.claude_bin, "-p", prompt, "--model", self.model],
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
            )

            if result.returncode != 0:
                logger.error(f"Claude error: {result.stderr}")
                return None

            # Parse JSON response
            response_text = result.stdout.strip()
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            json_str = response_text[json_start:json_end]

            decision_data = json.loads(json_str)

            # Validate against schema
            decision = DecisionSchema(**decision_data)
            logger.info(f"✓ Claude decision: {decision.action} (confidence: {decision.confidence})")

            return decision

        except subprocess.TimeoutExpired:
            logger.error(f"Claude timeout after {self.timeout_sec}s")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response: {e}")
            return None
        except Exception as e:
            logger.error(f"AI decision error: {e}", exc_info=True)
            return None

    async def check_trailing_sl(self, position: Dict, current_price: float) -> str:
        """
        Query Claude to decide on trailing SL / position exit

        Returns: "HOLD" | "MOVE_SL" | "EXIT"
        """
        try:
            prompt = f"""
Current position:
- Entry: {position['entry_price']}
- Current: {current_price}
- SL: {position['stop_loss']}
- Target: {position['target']}
- P&L: {position['pnl_pct']:.2f}%

Decide: HOLD (keep position) / MOVE_SL (trail stop) / EXIT (close now)?
Respond with JSON: {{"action": "HOLD|MOVE_SL|EXIT", "reason": "..."}}
"""
            result = subprocess.run(
                [self.claude_bin, "-p", prompt, "--model", self.model],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0:
                response_text = result.stdout.strip()
                json_start = response_text.find("{")
                json_end = response_text.rfind("}") + 1
                json_str = response_text[json_start:json_end]
                data = json.loads(json_str)
                return data.get("action", "HOLD")

            return "HOLD"
        except Exception as e:
            logger.error(f"Trailing SL check error: {e}")
            return "HOLD"

    async def learn_from_trades(self, trades: List[Dict]) -> List[Dict]:
        """
        Analyze past trades and suggest rule improvements
        Called nightly at 03:00 UTC
        """
        try:
            # Calculate stats
            total_trades = len(trades)
            winning = [t for t in trades if t["pnl"] > 0]
            losing = [t for t in trades if t["pnl"] < 0]

            win_pct = len(winning) / total_trades * 100 if total_trades > 0 else 0
            avg_win = sum(t["pnl"] for t in winning) / len(winning) if winning else 0
            avg_loss = sum(t["pnl"] for t in losing) / len(losing) if losing else 0
            total_pnl = sum(t["pnl"] for t in trades)

            prompt = f"""
Analyze these last 30 days of trading stats:
- Total trades: {total_trades}
- Win rate: {win_pct:.1f}%
- Avg win: ${avg_win:.2f}
- Avg loss: ${avg_loss:.2f}
- Total P&L: ${total_pnl:.2f}

Recent trades (last 5):
{json.dumps(trades[-5:], indent=2)}

Suggest 1-3 rule changes to improve performance.
Respond with JSON: {{"suggestions": [<str>, <str>, ...], "priority": "high|medium|low"}}
"""
            result = subprocess.run(
                [self.claude_bin, "-p", prompt, "--model", self.model],
                capture_output=True,
                text=True,
                timeout=15,
            )

            if result.returncode == 0:
                response_text = result.stdout.strip()
                json_start = response_text.find("{")
                json_end = response_text.rfind("}") + 1
                json_str = response_text[json_start:json_end]
                data = json.loads(json_str)

                logger.info(f"💡 Learning suggestions: {data.get('suggestions')}")
                return data.get("suggestions", [])

            return []

        except Exception as e:
            logger.error(f"Learning error: {e}", exc_info=True)
            return []
