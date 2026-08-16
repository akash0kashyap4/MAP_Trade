"""
Multi-leg spread construction, economics, and pre-trade EV / hard gates.

Naked option buying is structurally negative-expectancy for most intraday
setups (theta + spread cost), which is the single biggest P&L leak in a
long-only bot. This module gives the trader three tools to plug that leak:

  1. build_spread()      — turn an ATM strike + option chain into the concrete
                           legs of a defined-risk structure (bull-call,
                           bear-put, iron-fly).
  2. spread_economics()  — net debit/credit, max profit, max loss, breakevens
                           and reward:risk for a set of legs, using real leg
                           premiums.
  3. naked_buy_ev() + passes_hard_gates() — an explicit expected-value filter
                           and hard confidence / VIX / liquidity gates that can
                           REJECT a naked buy before it is placed.

Everything here is pure and side-effect-free so it is fully unit-testable and
safe to call from both the live trader and the backtest engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

Side = Literal["buy", "sell"]


@dataclass
class Leg:
    """One leg of a spread. qty_ratio is in lots relative to the base size."""
    option_type: Literal["CE", "PE"]
    strike: int
    side: Side
    premium: float
    qty_ratio: int = 1


# ── Spread construction ─────────────────────────────────────────────────────
def build_spread(
    kind: str,
    atm: int,
    step: int,
    chain: dict,
    width: int = 2,
) -> Optional[list[Leg]]:
    """Build the legs for a named spread around `atm`.

    `chain` is a {strike: {"ce": {...}, "pe": {...}}} style lookup (or the
    dashboard row list) providing per-strike CE/PE premiums. `width` is the
    number of `step`s between the short/long strikes. Returns None if any
    required leg premium is missing.

    Supported kinds:
      - bull_call : +ATM CE, -(ATM+width) CE   (debit, moderately bullish)
      - bear_put  : +ATM PE, -(ATM-width) PE   (debit, moderately bearish)
      - iron_fly  : -ATM CE, -ATM PE, +(ATM+width) CE, +(ATM-width) PE
                    (credit, range-bound / pinned at ATM)
    """
    lut = _chain_lookup(chain)

    def prem(strike: int, ot: str) -> Optional[float]:
        leg = lut.get(strike, {}).get(ot.lower(), {}) or {}
        p = leg.get("ltp")
        return float(p) if isinstance(p, (int, float)) and p > 0 else None

    kind = kind.lower()
    if kind == "bull_call":
        long_p, short_p = prem(atm, "CE"), prem(atm + width * step, "CE")
        if long_p is None or short_p is None:
            return None
        return [
            Leg("CE", atm, "buy", long_p),
            Leg("CE", atm + width * step, "sell", short_p),
        ]
    if kind == "bear_put":
        long_p, short_p = prem(atm, "PE"), prem(atm - width * step, "PE")
        if long_p is None or short_p is None:
            return None
        return [
            Leg("PE", atm, "buy", long_p),
            Leg("PE", atm - width * step, "sell", short_p),
        ]
    if kind == "iron_fly":
        sc, sp = prem(atm, "CE"), prem(atm, "PE")
        lc, lp = prem(atm + width * step, "CE"), prem(atm - width * step, "PE")
        if None in (sc, sp, lc, lp):
            return None
        return [
            Leg("CE", atm, "sell", sc),
            Leg("PE", atm, "sell", sp),
            Leg("CE", atm + width * step, "buy", lc),
            Leg("PE", atm - width * step, "buy", lp),
        ]
    return None


def _chain_lookup(chain) -> dict:
    """Normalise either {strike: {ce,pe}} or [{strike, ce, pe}] into a dict."""
    if isinstance(chain, dict):
        # Already {strike: {...}} — but keys may be str; normalise to int.
        out = {}
        for k, v in chain.items():
            try:
                out[int(k)] = v
            except (TypeError, ValueError):
                continue
        return out
    if isinstance(chain, list):
        out = {}
        for row in chain:
            s = row.get("strike")
            if isinstance(s, (int, float)):
                out[int(s)] = {"ce": row.get("ce") or {}, "pe": row.get("pe") or {}}
        return out
    return {}


# ── Spread economics ────────────────────────────────────────────────────────
@dataclass
class SpreadEconomics:
    net_debit: float          # >0 = you pay (debit), <0 = you receive (credit)
    max_profit: float
    max_loss: float
    reward_risk: float
    breakevens: list[float]
    is_credit: bool


def spread_economics(legs: list[Leg], lot_size: int, lots: int = 1) -> SpreadEconomics:
    """Compute defined-risk economics for a list of legs (premium points).

    Debit spreads: max loss = net debit, max profit = width − net debit.
    Credit spreads (iron fly): max profit = net credit, max loss = width − credit.
    All values are in rupees for `lots` lots of `lot_size`.
    """
    qty = lot_size * max(1, lots)
    # Net premium in points: buys cost (+), sells receive (−).
    net_points = 0.0
    for leg in legs:
        sign = 1.0 if leg.side == "buy" else -1.0
        net_points += sign * leg.premium * leg.qty_ratio
    net_debit = round(net_points * qty, 2)

    strikes = sorted({leg.strike for leg in legs})
    # Vertical (2-leg) width, or wing width for the iron fly.
    width_pts = (max(strikes) - min(strikes)) if len(strikes) >= 2 else 0
    is_credit = net_points < 0

    if is_credit:
        # Iron fly / credit vertical: keep the credit if pinned; lose (width − credit).
        # For an iron fly the risked side is one wing width.
        ce_strikes = sorted({leg.strike for leg in legs if leg.option_type == "CE"})
        wing = (max(ce_strikes) - min(ce_strikes)) if len(ce_strikes) >= 2 else width_pts
        max_profit = round(-net_points * qty, 2)                 # credit received
        max_loss   = round((wing * qty) - max_profit, 2)
    else:
        # Debit vertical: risk the debit, cap profit at (width − debit).
        max_loss   = net_debit
        max_profit = round((width_pts * qty) - net_debit, 2)

    reward_risk = round(max_profit / max_loss, 2) if max_loss > 0 else 0.0

    # Breakeven(s): long strike ± net debit-per-share for verticals.
    breakevens: list[float] = []
    per_share = abs(net_points)
    if not is_credit and len(strikes) >= 1:
        long_leg = next((lg for lg in legs if lg.side == "buy"), None)
        if long_leg:
            if long_leg.option_type == "CE":
                breakevens = [round(long_leg.strike + per_share, 2)]
            else:
                breakevens = [round(long_leg.strike - per_share, 2)]
    elif is_credit:
        atm = min(strikes, key=lambda s: abs(s - (sum(strikes) / len(strikes))))
        breakevens = [round(atm - per_share, 2), round(atm + per_share, 2)]

    return SpreadEconomics(
        net_debit=net_debit,
        max_profit=max_profit,
        max_loss=max_loss,
        reward_risk=reward_risk,
        breakevens=breakevens,
        is_credit=is_credit,
    )


def settle_spread(legs: list[Leg], spot_at_exit: float, lot_size: int, lots: int = 1) -> float:
    """Realised P&L of a spread if held to `spot_at_exit` (expiry-style
    intrinsic settlement). Used by tests and the backtest path to prove a
    spread actually executes and settles across both legs."""
    qty = lot_size * max(1, lots)
    pnl_points = 0.0
    for leg in legs:
        if leg.option_type == "CE":
            intrinsic = max(0.0, spot_at_exit - leg.strike)
        else:
            intrinsic = max(0.0, leg.strike - spot_at_exit)
        # buy: pay premium now, receive intrinsic at exit. sell: reverse.
        sign = 1.0 if leg.side == "buy" else -1.0
        pnl_points += sign * (intrinsic - leg.premium) * leg.qty_ratio
    return round(pnl_points * qty, 2)


# ── Pre-trade EV filter for naked buys ──────────────────────────────────────
@dataclass
class EVResult:
    ev: float               # expected value in rupees per unit qty
    accept: bool
    reason: str


def naked_buy_ev(
    entry: float,
    sl: float,
    target: float,
    p_win: float,
    fees_per_unit: float = 0.0,
) -> EVResult:
    """Expected value of a naked long option, per unit quantity.

    EV = p_win * (target − entry) − (1 − p_win) * (entry − sl) − fees.
    A naked buy is only worth taking when EV is positive after costs. `p_win`
    is the model's win probability (e.g. derived from confidence). Rejects
    trades whose reward geometry can't overcome their loss leg.
    """
    if entry <= 0 or target <= entry or sl >= entry:
        return EVResult(ev=0.0, accept=False, reason="invalid entry/sl/target geometry")
    p_win = max(0.0, min(1.0, p_win))
    win_amt  = target - entry
    loss_amt = entry - sl
    ev = p_win * win_amt - (1.0 - p_win) * loss_amt - fees_per_unit
    ev = round(ev, 4)
    if ev <= 0:
        return EVResult(ev=ev, accept=False,
                        reason=f"negative EV ({ev:.2f}/unit) at p_win={p_win:.2f}")
    return EVResult(ev=ev, accept=True, reason=f"EV +{ev:.2f}/unit at p_win={p_win:.2f}")


def confidence_to_pwin(confidence: int) -> float:
    """Map AI confidence (1-10) to a win probability. Conservative: even a 10
    tops out at 0.70 so the EV filter stays honest about option-buying odds."""
    c = max(0, min(10, int(confidence or 0)))
    return round(0.30 + 0.04 * c, 3)   # conf 5 -> 0.50, conf 10 -> 0.70


# ── Hard gates (in addition to the daily circuit breaker) ───────────────────
def passes_hard_gates(
    confidence: int,
    vix: float,
    atm_oi: float,
    *,
    min_confidence: int = 4,
    vix_ceiling: float = 30.0,
    min_liquidity_oi: float = 0.0,
) -> tuple[bool, str]:
    """Cheap, explicit pre-AI-trust gates. These are NOT meant to make the bot
    passive — the defaults are deliberately loose (conf>=4, VIX<=30) so normal
    setups pass — they only block the genuinely dangerous extremes: no-
    conviction signals, panic-level VIX, and illiquid strikes with no OI.

    Returns (passed, reason)."""
    c = int(confidence or 0)
    if c < min_confidence:
        return False, f"confidence {c} < floor {min_confidence}"
    if isinstance(vix, (int, float)) and vix > 0 and vix > vix_ceiling:
        return False, f"VIX {vix:.1f} > ceiling {vix_ceiling}"
    if min_liquidity_oi > 0 and isinstance(atm_oi, (int, float)) and 0 < atm_oi < min_liquidity_oi:
        return False, f"ATM OI {atm_oi:.0f} < liquidity floor {min_liquidity_oi:.0f}"
    return True, "hard gates passed"
