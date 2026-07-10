"""Tests for bot/fees.py — Indian options cost model."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.fees import apply_slippage, calc_round_trip_fees, realistic_pnl


class TestApplySlippage:
    def test_buy_increases_premium(self):
        result = apply_slippage(100.0, "buy")
        assert result > 100.0

    def test_sell_decreases_premium(self):
        result = apply_slippage(100.0, "sell")
        assert result < 100.0

    def test_zero_premium_unchanged(self):
        assert apply_slippage(0.0, "buy") == 0.0
        assert apply_slippage(0.0, "sell") == 0.0

    def test_custom_slippage(self):
        result = apply_slippage(100.0, "buy", slippage_pct=0.01)
        assert abs(result - 101.0) < 0.01


class TestCalcRoundTripFees:
    def test_fees_positive(self):
        fees = calc_round_trip_fees(100.0, 120.0, 75)
        assert fees["total"] > 0

    def test_brokerage_is_40(self):
        fees = calc_round_trip_fees(100.0, 120.0, 75)
        assert fees["brokerage"] == 40.0

    def test_stt_on_sell_side(self):
        # STT = 0.0625% of sell-side premium * qty
        fees = calc_round_trip_fees(100.0, 120.0, 75)
        expected_stt = 120.0 * 75 * 0.000625
        assert abs(fees["stt"] - round(expected_stt, 2)) < 0.01

    def test_gst_applied(self):
        fees = calc_round_trip_fees(100.0, 120.0, 75)
        assert fees["gst"] > 0

    def test_all_keys_present(self):
        fees = calc_round_trip_fees(100.0, 120.0, 75)
        for key in ("brokerage", "stt", "txn", "sebi", "stamp", "gst", "total"):
            assert key in fees

    def test_bse_txn_rate_different(self):
        nse = calc_round_trip_fees(100.0, 120.0, 75, exchange="NSE")
        bse = calc_round_trip_fees(100.0, 120.0, 75, exchange="BSE")
        assert nse["txn"] != bse["txn"]


class TestRealisticPnl:
    def test_winning_trade_net_positive(self):
        result = realistic_pnl(100.0, 150.0, 75)
        assert result["pnl_raw"] > 0
        assert result["pnl_final"] < result["pnl_raw"]  # fees always reduce

    def test_losing_trade_larger_loss_after_fees(self):
        result = realistic_pnl(100.0, 80.0, 75)
        assert result["pnl_raw"] < 0
        assert result["pnl_final"] < result["pnl_raw"]

    def test_pnl_final_equals_raw_minus_fees(self):
        result = realistic_pnl(100.0, 120.0, 75)
        expected = round(result["pnl_raw"] - result["fees"]["total"], 2)
        assert abs(result["pnl_final"] - expected) < 0.01
