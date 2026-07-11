"""
Market Context Builder
Prepare trading context for Claude AI
"""

import logging
from typing import Dict, List
from indicators.calculator import IndicatorCalculator

logger = logging.getLogger(__name__)


class StrategyContext:
    """Build market context for AI decision"""

    @staticmethod
    def build_context(
        current_price: float,
        candles: List[Dict],
        positions: List[Dict],
        portfolio_value: float,
        global_cues: Dict = None,
    ) -> Dict:
        """
        Build comprehensive market context for Claude

        Returns a dict with all relevant trading information
        """
        if len(candles) < 26:
            logger.warning("Not enough candles for indicators")
            return {}

        # Extract OHLCV
        close = [c["close"] for c in candles]
        high = [c["high"] for c in candles]
        low = [c["low"] for c in candles]
        volume = [c["volume"] for c in candles]

        # Calculate indicators
        indicators = IndicatorCalculator.calculate_all(candles)

        # Price structure (5m + 15m swings)
        structure = StrategyContext._analyze_structure(close, high, low)

        # Support & Resistance
        support_resistance = StrategyContext._find_sr_levels(close)

        context = {
            "timestamp": candles[-1].get("time"),
            "current_price": current_price,
            "candles_1h": candles,  # Last 60 x 1m = 60 min history
            "indicators": indicators,
            "structure": structure,
            "support_resistance": support_resistance,
            "positions": positions,
            "portfolio_value": portfolio_value,
            "cash_available": portfolio_value - sum(p.get("entry_price", 0) * p.get("quantity", 0) for p in positions),
            "global_cues": global_cues or {},
        }

        return context

    @staticmethod
    def _analyze_structure(close: List[float], high: List[float], low: List[float]) -> Dict:
        """Analyze price structure (swings, breakouts, etc)"""
        return {
            "current_close": close[-1],
            "5m_high": max(close[-12:]),  # Last 12 x 5m = 1 hour
            "5m_low": min(close[-12:]),
            "15m_high": max(close[-36:]) if len(close) >= 36 else max(close),
            "15m_low": min(close[-36:]) if len(close) >= 36 else min(close),
            "trend": "up" if close[-1] > close[-5] else "down",
            "momentum": "strong" if abs(close[-1] - close[-5]) / close[-5] > 0.01 else "weak",
        }

    @staticmethod
    def _find_sr_levels(close: List[float], num_levels: int = 3) -> Dict:
        """Find support and resistance levels"""
        sorted_close = sorted(close[-30:])  # Last 30 candles

        resistance = sorted_close[-num_levels:] if len(sorted_close) >= num_levels else sorted_close
        support = sorted_close[:num_levels] if len(sorted_close) >= num_levels else sorted_close

        return {
            "resistance": list(reversed(resistance)),
            "support": list(reversed(support)),
        }
