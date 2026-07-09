from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Candle:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    oi: int


@dataclass
class Signal:
    action: str
    instrument: str
    confidence: int
    reasoning: str
    strike: Optional[int] = None
    expiry: Optional[str] = None
    entry_price_approx: Optional[float] = None
    sl_premium: Optional[float] = None
    target_premium: Optional[float] = None
    risk_reward: Optional[float] = None


@dataclass
class Trade:
    instrument: str
    action: str
    strike: int
    expiry: str
    entry_time: str
    entry_price: float
    quantity: int
    sl_price: float
    target_price: float
    trade_type: str = "paper"
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    pnl_raw: float = 0.0
    pnl_final: float = 0.0
    signal_id: Optional[int] = None


@dataclass
class Position:
    instrument: str
    strike: int
    option_type: str
    expiry: str
    entry_price: float
    current_price: float
    quantity: int
    sl_price: float
    target_price: float
    entry_time: str
    signal_id: Optional[int] = None

    @property
    def pnl(self) -> float:
        return (self.current_price - self.entry_price) * self.quantity

    def to_dict(self) -> dict:
        return {
            "instrument": self.instrument,
            "strike": self.strike,
            "type": self.option_type,
            "expiry": self.expiry,
            "entry": self.entry_price,
            "ltp": self.current_price,
            "pnl": self.pnl,
            "sl": self.sl_price,
            "target": self.target_price,
            "entry_time": self.entry_time,
        }
