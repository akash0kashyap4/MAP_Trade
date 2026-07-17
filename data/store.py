from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List
import pytz
from datetime import datetime
from config import INITIAL_CAPITAL

IST = pytz.timezone("Asia/Kolkata")


@dataclass
class PriceInfo:
    ltp: float = 0.0
    chg: float = 0.0
    chg_pct: float = 0.0
    prev_close: float = 0.0   # yesterday's close — used for daily change


class LiveStore:
    def __init__(self):
        self.prices: Dict[str, PriceInfo] = {
            "NIFTY":     PriceInfo(),
            "BANKNIFTY": PriceInfo(),
            "SENSEX":    PriceInfo(),
        }
        self.positions: List[dict] = []
        self.signals: List[dict] = []
        self.realized_pnl: float = 0.0      # today's realized P&L only (resets daily)
        self.cumulative_pnl: float = 0.0   # all-time realized P&L (loaded from DB at startup)
        self.initial_capital: float = float(INITIAL_CAPITAL)
        self.ai_status: str = "waiting"
        self.feed_status: str = "closed"
        self.premarket_bias: dict = {}
        self.next_check_time: str = ""
        self.option_prices: Dict[str, float] = {}
        self.last_tick_time: str = ""
        self.tick_count: int = 0

        # Candles & indicators per instrument (populated by REST poll)
        self.today_candles: Dict[str, List[list]] = {}
        self.indicators: Dict[str, dict] = {}
        self.today_volume: Dict[str, int] = {"NIFTY": 0, "BANKNIFTY": 0, "SENSEX": 0}
        self.india_vix: float = 0.0

        # Runtime override flags (survive until bot restart)
        self.bot_paused: bool = False
        self.new_entries_enabled: bool = True

        # Today's news pulse (set by ai.news.NewsBrain.scan)
        self.news_insight: dict = {}

        self.using_mock_options: bool = False
        self.using_mock_chain: bool = False

    def set_prev_close(self, instrument: str, close: float):
        """Set yesterday's close — called once at startup."""
        info = self.prices.get(instrument)
        if info and close > 0:
            info.prev_close = close

    def update_price(self, instrument: str, ltp: float):
        info = self.prices.get(instrument)
        if not info:
            return
        info.ltp = ltp
        if info.prev_close > 0:
            info.chg     = round(ltp - info.prev_close, 2)
            info.chg_pct = round(info.chg / info.prev_close * 100, 2)

    def update_candles(self, instrument: str, candles: list):
        self.today_candles[instrument] = candles

    def update_volume(self, instrument: str, vol: int):
        if vol > 0:
            self.today_volume[instrument] = vol

    def update_indicators(self, instrument: str, ind: dict):
        self.indicators[instrument] = ind

    def add_signal(self, signal: dict):
        self.signals.insert(0, signal)
        if len(self.signals) > 50:
            self.signals.pop()

    def add_position(self, position: dict):
        self.positions.append(position)

    def remove_position(self, instrument: str, strike: int, option_type: str):
        self.positions = [
            p for p in self.positions
            if not (p["instrument"] == instrument
                    and p["strike"] == strike
                    and p["type"] == option_type)
        ]

    @property
    def unrealized_pnl(self) -> float:
        return sum(p.get("pnl", 0.0) for p in self.positions)

    @property
    def total_pnl(self) -> float:
        return self.realized_pnl + self.unrealized_pnl

    @property
    def capital_locked(self) -> float:
        """Capital currently tied up in open positions (entry premium × qty)."""
        return sum(p.get("entry", 0) * p.get("quantity", 0) for p in self.positions)

    @property
    def capital_available(self) -> float:
        """Free capital = initial + all-time realized P&L − locked in open positions."""
        return self.initial_capital + self.cumulative_pnl - self.capital_locked

    @property
    def capital_used_pct(self) -> float:
        return round(self.capital_locked / self.initial_capital * 100, 1) if self.initial_capital else 0.0

    @property
    def current_capital(self) -> float:
        """Total portfolio value = initial + all-time realized + unrealized."""
        return self.initial_capital + self.cumulative_pnl + self.unrealized_pnl

    def get_daily_summary(self) -> dict:
        return {
            "realized":          self.realized_pnl,
            "unrealized":        self.unrealized_pnl,
            "total":             self.total_pnl,
            "positions":         len(self.positions),
            "signals":           len(self.signals),
            "initial_capital":   self.initial_capital,
            "capital_locked":    round(self.capital_locked, 2),
            "capital_available": round(self.capital_available, 2),
            "capital_used_pct":  self.capital_used_pct,
            "current_capital":   round(self.current_capital, 2),
        }

    def reset_daily(self):
        self.positions      = []
        self.signals        = []
        self.realized_pnl   = 0.0   # today's P&L resets; cumulative_pnl is preserved
        self.ai_status      = "waiting"
        self.today_candles  = {}
        self.indicators     = {}
        self.premarket_bias = {}
        self.today_volume   = {"NIFTY": 0, "BANKNIFTY": 0, "SENSEX": 0}
        self.using_mock_options = False
        self.using_mock_chain   = False
        # bot_paused and new_entries_enabled are operator controls — intentionally NOT reset daily

    @property
    def using_mock_data(self) -> bool:
        return self.using_mock_options or self.using_mock_chain

    @property
    def trading_mode(self) -> str:
        """Current trading mode, derived from live config so it can never drift."""
        from config import TRADING
        return "paper" if TRADING.get("paper_trade", True) else "live"

    def sse_payload(self) -> dict:
        # Last 15 candles for NIFTY (primary display instrument)
        nifty_candles = self.today_candles.get("NIFTY", [])[-15:]
        candles_fmt = [
            {
                "time":   str(c[0])[11:19],
                "open":   round(float(c[1]), 2),
                "high":   round(float(c[2]), 2),
                "low":    round(float(c[3]), 2),
                "close":  round(float(c[4]), 2),
                "volume": int(c[5]) if c[5] else 0,
            }
            for c in nifty_candles
        ]

        return {
            "ts": datetime.now(IST).isoformat(),
            "prices": {
                k: {"ltp": v.ltp, "chg": v.chg, "chg_pct": v.chg_pct}
                for k, v in self.prices.items()
            },
            "candles":    candles_fmt,
            "using_mock_data": self.using_mock_data,
            "indicators": self.indicators.get("NIFTY", {}),
            "positions":  self.positions,
            "signals":    self.signals[:10],
            "pnl": {
                "realized":   self.realized_pnl,
                "unrealized": self.unrealized_pnl,
                "total":      self.total_pnl,
            },
            "capital": {
                "initial":   self.initial_capital,
                "current":   round(self.current_capital, 2),
                "locked":    round(self.capital_locked, 2),
                "available": round(self.capital_available, 2),
                "used_pct":  self.capital_used_pct,
            },
            "volume":       self.today_volume,
            "ai_status":    self.ai_status,
            "feed_status":  self.feed_status,
            "bot_paused":   self.bot_paused,
            "new_entries":  self.new_entries_enabled,
            "trading_mode": self.trading_mode,
            "today_bias":   self.premarket_bias.get("bias", "NEUTRAL"),
            "next_check":   self.next_check_time,
            "last_tick":    self.last_tick_time,
            "tick_count":   self.tick_count,
            "india_vix":    self.india_vix,
            "news":         self.news_insight,
        }


store = LiveStore()
