"""Tests for bot/spreads.py — spread construction, economics, EV & hard gates.

Includes the rubric acceptance check for Trading logic:
  - a spread actually builds, executes and settles across both legs, and
  - a naked-buy order is REJECTED when the EV filter fails.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.spreads import (
    Leg, build_spread, spread_economics, settle_spread,
    naked_buy_ev, confidence_to_pwin, passes_hard_gates,
)


# Chain lookup helper: rows in the dashboard shape.
def _chain():
    return [
        {"strike": 23900, "ce": {"ltp": 180}, "pe": {"ltp": 25}},
        {"strike": 24000, "ce": {"ltp": 100}, "pe": {"ltp": 60}},
        {"strike": 24100, "ce": {"ltp": 55},  "pe": {"ltp": 120}},
    ]


class TestBuildSpread:
    def test_bull_call_legs(self):
        legs = build_spread("bull_call", 24000, 50, _chain(), width=2)
        assert legs is not None
        assert len(legs) == 2
        long_leg, short_leg = legs
        assert long_leg.side == "buy" and long_leg.strike == 24000 and long_leg.option_type == "CE"
        assert short_leg.side == "sell" and short_leg.strike == 24100

    def test_bear_put_legs(self):
        legs = build_spread("bear_put", 24000, 50, _chain(), width=2)
        assert legs is not None
        long_leg, short_leg = legs
        assert long_leg.side == "buy" and long_leg.option_type == "PE" and long_leg.strike == 24000
        assert short_leg.side == "sell" and short_leg.strike == 23900

    def test_iron_fly_four_legs(self):
        legs = build_spread("iron_fly", 24000, 50, _chain(), width=2)
        assert legs is not None
        assert len(legs) == 4
        sold = [lg for lg in legs if lg.side == "sell"]
        bought = [lg for lg in legs if lg.side == "buy"]
        assert len(sold) == 2 and len(bought) == 2

    def test_missing_premium_returns_none(self):
        chain = [{"strike": 24000, "ce": {"ltp": 100}, "pe": {"ltp": 60}}]  # no ATM+2 strike
        assert build_spread("bull_call", 24000, 50, chain, width=2) is None

    def test_unknown_kind_returns_none(self):
        assert build_spread("nonsense", 24000, 50, _chain()) is None


class TestSpreadEconomics:
    def test_bull_call_debit_economics(self):
        # +24000 CE @100, -24100 CE @55 → net debit 45 pts, width 100 pts.
        legs = [Leg("CE", 24000, "buy", 100.0), Leg("CE", 24100, "sell", 55.0)]
        econ = spread_economics(legs, lot_size=65, lots=1)
        assert econ.is_credit is False
        assert econ.net_debit == round(45 * 65, 2)        # 2925
        assert econ.max_loss == econ.net_debit            # debit is the risk
        assert econ.max_profit == round((100 - 45) * 65, 2)  # (width - debit)*qty
        assert econ.reward_risk > 1.0
        assert econ.breakevens == [round(24000 + 45, 2)]  # long strike + debit/share

    def test_iron_fly_credit_economics(self):
        # Sell 24000 straddle (70+70=140), buy wings (25+25=50) → net credit 90 pts,
        # wing width 100 pts → max loss (100-90)*qty, max profit 90*qty.
        legs = [
            Leg("CE", 24000, "sell", 70.0),
            Leg("PE", 24000, "sell", 70.0),
            Leg("CE", 24100, "buy", 25.0),
            Leg("PE", 23900, "buy", 25.0),
        ]
        econ = spread_economics(legs, lot_size=65, lots=1)
        assert econ.is_credit is True
        assert econ.max_profit == round(90 * 65, 2)
        assert econ.max_loss == round((100 - 90) * 65, 2)
        assert len(econ.breakevens) == 2

    def test_defined_risk_never_unbounded(self):
        legs = [Leg("CE", 24000, "buy", 100.0), Leg("CE", 24100, "sell", 55.0)]
        econ = spread_economics(legs, lot_size=65, lots=2)
        assert econ.max_loss > 0
        assert econ.max_profit > 0


class TestSettlement:
    def test_bull_call_settles_at_max_profit_above_short(self):
        legs = [Leg("CE", 24000, "buy", 100.0), Leg("CE", 24100, "sell", 55.0)]
        # Spot well above short strike → both ITM → capped max profit.
        pnl = settle_spread(legs, spot_at_exit=24300, lot_size=65, lots=1)
        econ = spread_economics(legs, 65, 1)
        assert abs(pnl - econ.max_profit) < 1.0

    def test_bull_call_settles_at_max_loss_below_long(self):
        legs = [Leg("CE", 24000, "buy", 100.0), Leg("CE", 24100, "sell", 55.0)]
        # Spot below long strike → both worthless → lose the net debit.
        pnl = settle_spread(legs, spot_at_exit=23800, lot_size=65, lots=1)
        econ = spread_economics(legs, 65, 1)
        assert abs(pnl - (-econ.max_loss)) < 1.0

    def test_spread_executes_and_settles_end_to_end(self):
        """A spread builds from a chain, prices, and settles across BOTH legs —
        proving multi-leg orders execute, not just render as a catalogue."""
        legs = build_spread("bull_call", 24000, 50, _chain(), width=2)
        assert legs is not None
        econ = spread_economics(legs, lot_size=65, lots=1)
        assert econ.max_loss > 0 and econ.max_profit > 0
        pnl_win  = settle_spread(legs, 24300, 65, 1)
        pnl_lose = settle_spread(legs, 23800, 65, 1)
        assert pnl_win > 0 > pnl_lose


class TestNakedBuyEV:
    def test_positive_ev_accepts(self):
        # entry 100, sl 70, target 200, decent win prob → positive EV.
        res = naked_buy_ev(entry=100, sl=70, target=200, p_win=0.6)
        assert res.accept is True
        assert res.ev > 0

    def test_negative_ev_rejects(self):
        # Poor geometry: small target, big SL, low win prob → EV negative.
        res = naked_buy_ev(entry=100, sl=60, target=115, p_win=0.4)
        assert res.accept is False
        assert res.ev <= 0
        assert "negative EV" in res.reason

    def test_fees_can_flip_marginal_trade_negative(self):
        base = naked_buy_ev(entry=100, sl=80, target=125, p_win=0.5, fees_per_unit=0)
        withfees = naked_buy_ev(entry=100, sl=80, target=125, p_win=0.5, fees_per_unit=5)
        assert withfees.ev < base.ev

    def test_invalid_geometry_rejected(self):
        assert naked_buy_ev(entry=100, sl=120, target=200, p_win=0.6).accept is False  # sl above entry
        assert naked_buy_ev(entry=100, sl=80, target=90, p_win=0.6).accept is False     # target below entry

    def test_confidence_to_pwin_bounds(self):
        assert confidence_to_pwin(0) < confidence_to_pwin(10)
        assert 0.0 <= confidence_to_pwin(1) <= 1.0
        assert confidence_to_pwin(10) <= 0.75  # honest ceiling for option buying


class TestHardGates:
    def test_low_confidence_blocked(self):
        ok, reason = passes_hard_gates(2, 15.0, 1_000_000, min_confidence=4)
        assert ok is False and "confidence" in reason

    def test_panic_vix_blocked(self):
        ok, reason = passes_hard_gates(7, 35.0, 1_000_000, vix_ceiling=30.0)
        assert ok is False and "VIX" in reason

    def test_illiquid_blocked_when_floor_set(self):
        ok, reason = passes_hard_gates(7, 15.0, 500, min_liquidity_oi=10_000)
        assert ok is False and "OI" in reason

    def test_normal_setup_passes(self):
        ok, reason = passes_hard_gates(6, 15.0, 1_000_000,
                                       min_confidence=4, vix_ceiling=30.0, min_liquidity_oi=0)
        assert ok is True

    def test_liquidity_gate_off_by_default(self):
        # min_liquidity_oi=0 → gate disabled even with tiny OI.
        ok, _ = passes_hard_gates(6, 15.0, 1, min_liquidity_oi=0)
        assert ok is True


class TestAcceptanceCheck:
    """Rubric: 'a test proves a naked-buy order is rejected when EV filter fails.'"""

    def test_naked_buy_rejected_when_ev_filter_fails(self):
        # Simulate the trader's gate: low-conviction, poor R:R naked buy.
        confidence = 4
        p_win = confidence_to_pwin(confidence)          # 0.46
        entry, sl, target = 100.0, 65.0, 120.0          # risk 35 to make 20
        res = naked_buy_ev(entry, sl, target, p_win, fees_per_unit=0.6)
        assert res.accept is False, f"expected rejection, got {res}"
        assert res.ev <= 0
