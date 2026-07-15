"""End-to-end tests for backtest_orchestrator using the offline CSV provider.

These are deterministic (no network, no tokens) and prove the full chain works:
    strategy code -> compile -> provider -> resolver -> engine -> trades -> metrics

The CSV provider returns an empty option chain (like Groww), so these also
exercise the resolver's synthetic-contract fallback: without it the engine
places zero trades.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import polars as pl
import pytest

from backtest_orchestrator import run_backtest, _compile_strategy_code
from bhav.data.providers.local_csv_provider import LocalCsvProvider

D = "2025-01-16"
UND = "NSE_INDEX|Nifty 50"

BUY_OPEN_CE = """
from bhav.engine.strategy import Strategy, Context

class BuyOpenCE(Strategy):
    name = "BuyOpenCE"
    def on_day_start(self, ctx: Context):
        self._done = False
    def on_bar(self, ctx: Context):
        if not getattr(self, "_done", False):
            if ctx.buy_option(option_type="CE", strike_offset=0, lots=1):
                self._done = True

strategy = BuyOpenCE()
"""


def _frame(rows):
    return pl.DataFrame(
        rows,
        schema=["timestamp", "open", "high", "low", "close", "volume", "oi"],
        orient="row",
    )


def _seed_csv(tmp: str) -> LocalCsvProvider:
    """Write one day of spot + matching 24000CE option candles to a CSV dir."""
    prov = LocalCsvProvider(tmp)
    spot = _frame([
        [f"{D}T09:15:00+0530", 24000.0, 24010.0, 23990.0, 24000.0, 100, 0],
        [f"{D}T09:16:00+0530", 24000.0, 24030.0, 23995.0, 24020.0, 100, 0],
        [f"{D}T15:15:00+0530", 24080.0, 24090.0, 24070.0, 24085.0, 100, 0],
    ])
    spot.write_parquet(prov.spot_dir / f"{prov._sanitize_filename(UND)}_{D}.parquet")

    opt_key = f"{UND}|{D}|24000|CE"
    opt = _frame([
        [f"{D}T09:15:00+0530", 120.0, 122.0, 118.0, 120.0, 50, 0],
        [f"{D}T09:16:00+0530", 121.0, 135.0, 120.0, 133.0, 50, 0],
        [f"{D}T15:15:00+0530", 180.0, 185.0, 178.0, 182.0, 50, 0],
    ])
    opt.write_parquet(prov.opt_dir / f"{prov._sanitize_filename(opt_key)}_{D}.parquet")
    return prov


def test_compile_rejects_missing_strategy_var():
    with pytest.raises(ValueError, match="strategy"):
        _compile_strategy_code("x = 1")


def test_compile_rejects_syntax_error():
    with pytest.raises(ValueError):
        _compile_strategy_code("def (:")


def test_end_to_end_places_and_closes_a_trade():
    with TemporaryDirectory() as tmp:
        _seed_csv(tmp)
        result = run_backtest(
            strategy_code=BUY_OPEN_CE,
            start=D, end=D,
            underlying=UND,
            capital=500_000,
            broker="csv",
            csv_dir=Path(tmp),
        )
    assert result.total_trades == 1
    assert result.wins == 1
    # Bought ~120.05, squared off ~181.95, lot 65 -> ~+4000 after costs.
    assert result.total_pnl > 0
    assert result.trades[0]["reason"] == "eod_square_off"
    assert result.trades[0]["quantity"] == 65


def test_end_to_end_empty_dir_runs_without_trades():
    """No data -> pipeline must not crash, just produce zero trades."""
    with TemporaryDirectory() as tmp:
        result = run_backtest(
            strategy_code=BUY_OPEN_CE,
            start=D, end=D,
            underlying=UND,
            broker="csv",
            csv_dir=Path(tmp),
        )
    assert result.total_trades == 0


def test_bad_dates_rejected():
    with TemporaryDirectory() as tmp:
        with pytest.raises(ValueError):
            run_backtest(
                strategy_code=BUY_OPEN_CE,
                start="2025-02-01", end="2025-01-01",  # start after end
                broker="csv", csv_dir=Path(tmp),
            )
