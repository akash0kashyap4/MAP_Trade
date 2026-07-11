"""
Pydantic schemas for Claude AI decision validation
"""

from pydantic import BaseModel, Field, validator
from typing import Optional


class DecisionSchema(BaseModel):
    """Claude's trading decision response"""

    action: str = Field(..., description="BUY_MARKET | SELL_MARKET | HOLD")
    confidence: float = Field(..., ge=0, le=1, description="Confidence 0-1")
    entry_price: Optional[float] = Field(None, description="Entry price for BUY")
    stop_loss_pct: Optional[float] = Field(None, description="SL as % below entry")
    target_pct: Optional[float] = Field(None, description="Target as % above entry")
    reason: str = Field(..., description="Why this decision")
    risk_reward_ratio: Optional[float] = Field(None, description="Target/SL ratio")

    @validator("action")
    def validate_action(cls, v):
        if v not in ["BUY_MARKET", "SELL_MARKET", "HOLD"]:
            raise ValueError("Invalid action")
        return v

    @validator("stop_loss_pct")
    def validate_sl(cls, v):
        if v is not None and (v <= 0 or v > 0.20):  # SL between 0.1% and 20%
            raise ValueError("SL must be 0.1% to 20%")
        return v

    @validator("target_pct")
    def validate_target(cls, v):
        if v is not None and (v <= 0 or v > 1.0):  # Target between 0.1% and 100%
            raise ValueError("Target must be 0.1% to 100%")
        return v


class TradeSchema(BaseModel):
    """Trade execution and history"""

    timestamp: str
    action: str  # BUY_MARKET / SELL_MARKET
    entry_price: float
    quantity: float
    stop_loss: float
    target: float
    status: str  # OPEN / CLOSED / SL_HIT / TARGET_HIT
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    fees: Optional[float] = None
    claude_decision: Optional[str] = None  # Full decision JSON


class PositionSchema(BaseModel):
    """Active position tracking"""

    pair: str
    entry_price: float
    current_price: float
    quantity: float
    stop_loss: float
    target: float
    pnl: float
    pnl_pct: float
    entry_time: str
    status: str  # OPEN / TRAILING / PROFIT_ZONE
