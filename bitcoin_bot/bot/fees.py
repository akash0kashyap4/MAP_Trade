"""
Binance Crypto Trading Fees Model
Calculate realistic trading costs
"""

import logging

logger = logging.getLogger(__name__)


class FeeCalculator:
    """Calculate trading fees for Binance"""

    BINANCE_TAKER_FEE = 0.001  # 0.1%
    BINANCE_MAKER_FEE = 0.001  # 0.1%
    DEFAULT_SLIPPAGE = 0.003  # 0.3% slippage on entry

    @staticmethod
    def calculate_entry_cost(entry_price: float, quantity: float) -> dict:
        """
        Calculate total cost including slippage and fees
        """
        gross_cost = entry_price * quantity
        slippage_cost = gross_cost * FeeCalculator.DEFAULT_SLIPPAGE
        fee_cost = gross_cost * FeeCalculator.BINANCE_TAKER_FEE

        total_cost = gross_cost + slippage_cost + fee_cost

        return {
            "gross_cost": gross_cost,
            "slippage": slippage_cost,
            "fee": fee_cost,
            "total_cost": total_cost,
            "effective_entry": total_cost / quantity,
        }

    @staticmethod
    def calculate_exit_proceeds(exit_price: float, quantity: float) -> dict:
        """
        Calculate proceeds after fees and slippage
        """
        gross_proceeds = exit_price * quantity
        slippage_deduction = gross_proceeds * FeeCalculator.DEFAULT_SLIPPAGE
        fee_deduction = gross_proceeds * FeeCalculator.BINANCE_TAKER_FEE

        total_proceeds = gross_proceeds - slippage_deduction - fee_deduction

        return {
            "gross_proceeds": gross_proceeds,
            "slippage": slippage_deduction,
            "fee": fee_deduction,
            "total_proceeds": total_proceeds,
            "effective_exit": total_proceeds / quantity,
        }

    @staticmethod
    def calculate_pnl(entry_price: float, exit_price: float, quantity: float) -> dict:
        """
        Calculate realistic P&L including all costs
        """
        entry = FeeCalculator.calculate_entry_cost(entry_price, quantity)
        exit_calc = FeeCalculator.calculate_exit_proceeds(exit_price, quantity)

        gross_pnl = (exit_price - entry_price) * quantity
        total_fees = entry["fee"] + exit_calc["fee"]
        total_slippage = entry["slippage"] + exit_calc["slippage"]
        net_pnl = gross_pnl - total_fees - total_slippage

        return {
            "gross_pnl": gross_pnl,
            "fees": total_fees,
            "slippage": total_slippage,
            "net_pnl": net_pnl,
            "pnl_pct": (net_pnl / entry["total_cost"]) * 100,
        }
