"""
Pydantic schemas for AI responses. Every Claude reply is validated against these
before it can influence trading. Invalid JSON -> NO_TRADE with a recorded reason.
"""
from __future__ import annotations
from typing import Optional, Literal
from pydantic import BaseModel, Field, field_validator, ValidationError


class DecisionSchema(BaseModel):
    action: Literal["BUY_CE", "BUY_PE", "HOLD", "EXIT_ALL", "NO_TRADE"]
    instrument: Optional[str] = None
    strike: Optional[int] = None
    expiry: Optional[str] = None
    confidence: int = Field(ge=0, le=10)
    trend_read: Optional[str] = None
    entry_trigger: Optional[str] = None
    reasoning: str = ""
    sl_premium: Optional[float] = None
    target_premium: Optional[float] = None
    risk_reward: Optional[float] = None

    # -1 = one strike ITM (higher delta), 0 = ATM, +1 = one strike OTM (cheaper).
    # AI picks it — clamped to [-2, +2] to avoid deep-ITM/OTM disasters.
    strike_offset: int = Field(default=0, ge=-2, le=2)

    # "current" = nearest weekly (default, high theta), "next" = following week
    # (lower theta, better for Mon/Tue swing buys).
    expiry_pref: Literal["current", "next"] = "current"

    @field_validator("action", mode="before")
    @classmethod
    def normalize_action(cls, v):
        if isinstance(v, str):
            return v.strip().upper()
        return v

    @field_validator("confidence", mode="before")
    @classmethod
    def coerce_confidence(cls, v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0


class PremarketSchema(BaseModel):
    bias: Literal["BULLISH", "BEARISH", "NEUTRAL"] = "NEUTRAL"
    bias_strength: Optional[int] = Field(default=5, ge=1, le=10)
    risk_level: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    recommended_stance: Optional[str] = None
    reasoning: str = ""

    @field_validator("bias", "risk_level", mode="before")
    @classmethod
    def upper(cls, v):
        if isinstance(v, str):
            return v.strip().upper()
        return v


class TrailingSLSchema(BaseModel):
    # CUT_EARLY = exit losing/breakeven position because thesis is invalidated
    # (structure flipped, opposite BOS, momentum stalled). Distinct from EXIT
    # which is used when a profitable trade has run its course.
    action: Literal["HOLD", "MOVE_SL", "EXIT", "CUT_EARLY"] = "HOLD"
    new_sl: Optional[float] = None
    reason: str = ""

    @field_validator("action", mode="before")
    @classmethod
    def upper(cls, v):
        if isinstance(v, str):
            return v.strip().upper()
        return v


def validate_decision(raw: dict) -> tuple[dict, Optional[str]]:
    """
    Returns (validated_dict, error_str). error_str is None on success.
    On failure, the validated_dict is a safe NO_TRADE fallback so the
    caller can keep the trail going.
    """
    try:
        d = DecisionSchema(**raw).model_dump()
        # Hard guard: BUY_CE/BUY_PE with conf 0 is contradictory -> NO_TRADE
        if d["action"] in ("BUY_CE", "BUY_PE") and d["confidence"] < 1:
            d["action"] = "NO_TRADE"
            d["reasoning"] = "[Schema] action was BUY_* with confidence 0 - downgraded"
        return d, None
    except ValidationError as e:
        return (
            {
                "action": "NO_TRADE",
                "instrument": raw.get("instrument") if isinstance(raw, dict) else None,
                "confidence": 0,
                "reasoning": f"schema_validation_failed: {str(e)[:200]}",
            },
            str(e)[:300],
        )


def validate_premarket(raw: dict) -> dict:
    try:
        return PremarketSchema(**raw).model_dump()
    except ValidationError:
        return {"bias": "NEUTRAL", "risk_level": "HIGH",
                "reasoning": "schema validation failed - defaulting NEUTRAL/HIGH"}


def validate_trailing_sl(raw: dict) -> dict:
    try:
        return TrailingSLSchema(**raw).model_dump()
    except ValidationError:
        return {"action": "HOLD", "new_sl": None, "reason": "schema validation failed"}
