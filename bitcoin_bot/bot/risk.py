"""
Risk Management & Position Sizing
"""

import logging
import math

logger = logging.getLogger(__name__)


class RiskManager:
    """Position sizing and risk calculations"""

    @staticmethod
    def kelly_criterion(win_rate: float, avg_win: float, avg_loss: float) -> float:
        """
        Calculate Kelly fraction for position sizing
        f* = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
        """
        if avg_win <= 0:
            return 0

        kelly = (
            (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
        )
        return max(0, min(kelly, 0.25))  # Cap at 25% for safety

    @staticmethod
    def calculate_position_size(
        account_balance: float,
        entry_price: float,
        stop_loss_price: float,
        risk_pct: float = 0.02,
    ) -> float:
        """
        Calculate position size based on risk percentage

        Args:
            account_balance: Total account capital
            entry_price: Entry price
            stop_loss_price: Stop loss price
            risk_pct: Risk per trade as % of account (default 2%)

        Returns:
            Position size in base currency
        """
        risk_amount = account_balance * risk_pct
        price_risk = abs(entry_price - stop_loss_price)

        if price_risk <= 0:
            return 0

        position_size = risk_amount / price_risk
        return position_size

    @staticmethod
    def calculate_reward_ratio(
        entry_price: float,
        stop_loss_price: float,
        target_price: float,
    ) -> float:
        """Calculate risk:reward ratio"""
        risk = abs(entry_price - stop_loss_price)
        reward = abs(target_price - entry_price)

        if risk <= 0:
            return 0

        return reward / risk

    @staticmethod
    def check_position_limits(
        current_positions: int,
        max_positions: int,
        daily_loss: float,
        max_daily_loss: float,
    ) -> tuple[bool, str]:
        """
        Check if trade is allowed based on risk limits

        Returns:
            (allowed: bool, reason: str)
        """
        if current_positions >= max_positions:
            return False, f"Max positions ({max_positions}) reached"

        if daily_loss >= max_daily_loss:
            return False, f"Daily loss limit (${max_daily_loss}) reached"

        return True, "OK"

    @staticmethod
    def calculate_drawdown(peak: float, current: float) -> float:
        """Calculate drawdown percentage from peak"""
        if peak <= 0:
            return 0

        return ((current - peak) / peak) * 100
