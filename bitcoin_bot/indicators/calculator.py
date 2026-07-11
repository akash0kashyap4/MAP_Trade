"""
Technical Indicators Calculator
RSI, EMA, MACD, Bollinger Bands, ATR, Supertrend, VWAP
"""

import numpy as np
from typing import List, Dict, Tuple


class IndicatorCalculator:
    """Calculate technical indicators from OHLCV data"""

    @staticmethod
    def rsi(closes: List[float], period: int = 14) -> List[float]:
        """Relative Strength Index (0-100)"""
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])

        rsi_values = [np.nan] * (period - 1)

        for i in range(period - 1, len(closes)):
            if avg_loss == 0:
                rsi = 100 if avg_gain > 0 else 0
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))

            rsi_values.append(rsi)

            if i < len(closes) - 1:
                avg_gain = (avg_gain * (period - 1) + gains[i]) / period
                avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        return rsi_values

    @staticmethod
    def ema(closes: List[float], period: int = 21) -> List[float]:
        """Exponential Moving Average"""
        ema_values = []
        multiplier = 2 / (period + 1)

        # SMA for first value
        sma = np.mean(closes[:period])
        ema_values.append(sma)

        for i in range(period, len(closes)):
            ema = closes[i] * multiplier + ema_values[-1] * (1 - multiplier)
            ema_values.append(ema)

        return [np.nan] * (period - 1) + ema_values

    @staticmethod
    def macd(closes: List[float]) -> Dict[str, List[float]]:
        """MACD (Moving Average Convergence Divergence)"""
        ema12 = IndicatorCalculator.ema(closes, 12)
        ema26 = IndicatorCalculator.ema(closes, 26)

        macd_line = np.array(ema12) - np.array(ema26)
        signal = IndicatorCalculator.ema(list(macd_line), 9)

        return {
            "macd": macd_line,
            "signal": signal,
            "histogram": macd_line - np.array(signal),
        }

    @staticmethod
    def bollinger_bands(
        closes: List[float], period: int = 20, std_dev: float = 2.0
    ) -> Dict[str, List[float]]:
        """Bollinger Bands"""
        sma = np.convolve(closes, np.ones(period) / period, mode="valid")
        variance = []

        for i in range(period - 1, len(closes)):
            subset = closes[i - period + 1 : i + 1]
            variance.append(np.std(subset))

        upper = sma + (std_dev * np.array(variance))
        lower = sma - (std_dev * np.array(variance))

        return {
            "upper": list(upper),
            "middle": list(sma),
            "lower": list(lower),
        }

    @staticmethod
    def atr(high: List[float], low: List[float], close: List[float], period: int = 14) -> List[float]:
        """Average True Range"""
        tr_values = []

        for i in range(len(close)):
            if i == 0:
                tr = high[i] - low[i]
            else:
                tr = max(
                    high[i] - low[i],
                    abs(high[i] - close[i - 1]),
                    abs(low[i] - close[i - 1]),
                )
            tr_values.append(tr)

        atr_values = [np.nan] * (period - 1)
        atr_values.append(np.mean(tr_values[:period]))

        for i in range(period, len(tr_values)):
            atr = (atr_values[-1] * (period - 1) + tr_values[i]) / period
            atr_values.append(atr)

        return atr_values

    @staticmethod
    def supertrend(
        high: List[float], low: List[float], close: List[float], period: int = 10, multiplier: float = 3.0
    ) -> Dict[str, List[float]]:
        """Supertrend indicator"""
        hl_avg = (np.array(high) + np.array(low)) / 2
        atr_vals = IndicatorCalculator.atr(high, low, close, period)

        basic_ub = hl_avg + multiplier * np.array(atr_vals)
        basic_lb = hl_avg - multiplier * np.array(atr_vals)

        # Calculate final bands
        final_ub = [basic_ub[period - 1]]
        final_lb = [basic_lb[period - 1]]

        for i in range(period, len(close)):
            final_ub.append(
                basic_ub[i] if basic_ub[i] < final_ub[-1] or close[i - 1] > final_ub[-1] else final_ub[-1]
            )
            final_lb.append(
                basic_lb[i] if basic_lb[i] > final_lb[-1] or close[i - 1] < final_lb[-1] else final_lb[-1]
            )

        return {"upper": final_ub, "lower": final_lb}

    @staticmethod
    def vwap(high: List[float], low: List[float], close: List[float], volume: List[float]) -> List[float]:
        """Volume Weighted Average Price"""
        tp = (np.array(high) + np.array(low) + np.array(close)) / 3
        vwap_values = np.cumsum(tp * np.array(volume)) / np.cumsum(np.array(volume))
        return list(vwap_values)

    @staticmethod
    def calculate_all(candles: List[Dict]) -> Dict:
        """Calculate all indicators for a set of candles"""
        if len(candles) < 26:
            return {}

        close = [c["close"] for c in candles]
        high = [c["high"] for c in candles]
        low = [c["low"] for c in candles]
        volume = [c["volume"] for c in candles]

        return {
            "rsi": IndicatorCalculator.rsi(close)[-1],
            "ema9": IndicatorCalculator.ema(close, 9)[-1],
            "ema21": IndicatorCalculator.ema(close, 21)[-1],
            "ema50": IndicatorCalculator.ema(close, 50) if len(close) >= 50 else [None],
            "macd": IndicatorCalculator.macd(close),
            "bb": IndicatorCalculator.bollinger_bands(close),
            "atr": IndicatorCalculator.atr(high, low, close)[-1],
            "supertrend": IndicatorCalculator.supertrend(high, low, close),
            "vwap": IndicatorCalculator.vwap(high, low, close, volume)[-1],
        }
