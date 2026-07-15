"""Typer CLI entry point (refactored with provider support)."""
from __future__ import annotations

import importlib.util
import uuid
from datetime import date, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from bhav.data.cache import ParquetCache
from bhav.data.instruments import InstrumentResolver
from bhav.data.provider import BrokerDataProvider
from bhav.data.providers.groww_provider import GrowwDataProvider
from bhav.data.providers.local_csv_provider import LocalCsvProvider
from bhav.data.providers.upstox_provider import UpstoxProvider
from bhav.data.reader import DataReader
from bhav.data.underlyings import default_lot_size
from bhav.engine.bar_engine import BarEngine, EngineConfig
from bhav.metrics.report import compute_metrics
from bhav.output.writer import ResultWriter

app = typer.Typer(help="Bhav: NSE options backtester (provider-agnostic)", no_args_is_help=True)
console = Console()


@app.callback()
def _main() -> None:
    """Bhav: NSE options backtesting engine."""


def _load_strategy(path: Path):
    """Dynamically load strategy from Python file."""
    spec = importlib.util.spec_from_file_location("user_strategy", path)
    if spec is None or spec.loader is None:
        raise typer.BadParameter(f"Could not load strategy from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "strategy"):
        raise typer.BadParameter(f"{path} must expose a `strategy` variable")
    return mod.strategy


def _create_provider(
    broker: str,
    groww_token: str | None = None,
    upstox_token: str | None = None,
    csv_dir: Path | None = None,
) -> BrokerDataProvider:
    """Factory function to create appropriate provider.

    Args:
        broker: "groww", "upstox", or "csv"
        groww_token: Groww API token (optional)
        upstox_token: Upstox API token (required for Upstox)
        csv_dir: Directory for CSV provider

    Returns:
        BrokerDataProvider instance

    Raises:
        typer.BadParameter: On invalid broker or missing tokens
    """
    if broker == "groww":
        return GrowwDataProvider(api_token=groww_token)
    elif broker == "upstox":
        if not upstox_token:
            raise typer.BadParameter("--upstox-token or UPSTOX_TOKEN required for --broker upstox")
        return UpstoxProvider(token=upstox_token)
    elif broker == "csv":
        if not csv_dir:
            raise typer.BadParameter("--csv-dir required for --broker csv")
        return LocalCsvProvider(csv_dir)
    else:
        raise typer.BadParameter(f"Unknown broker: {broker}. Use 'groww', 'upstox', or 'csv'")


@app.command()
def run(
    strategy_path: Path = typer.Argument(..., help="Path to a Python file with `strategy = MyStrategy()`"),
    start: str = typer.Option(..., help="YYYY-MM-DD"),
    end: str = typer.Option(..., help="YYYY-MM-DD"),
    broker: str = typer.Option("groww", help="Data provider: 'groww' (default), 'upstox', or 'csv'"),
    groww_token: str | None = typer.Option(None, envvar="GROWW_TOKEN", help="Groww API token (optional for demo)"),
    upstox_token: str | None = typer.Option(None, envvar="UPSTOX_TOKEN", help="Upstox API token (required if broker=upstox)"),
    csv_dir: Path | None = typer.Option(None, help="CSV data directory (required if broker=csv)"),
    underlying: str = typer.Option("NSE_INDEX|Nifty 50"),
    capital: float = typer.Option(500_000),
    lot_size: int = typer.Option(0, help="Override lot size. 0 = auto-lookup from underlying."),
    warmup_days: int = typer.Option(0, help="Trading days before --start to feed the strategy (no trades placed)."),
    cache_dir: Path | None = typer.Option(Path("cache"), help="Directory for candle cache"),
    out_dir: Path = typer.Option(Path("runs")),
) -> None:
    """Run a backtest and write results to `runs/<run_id>/`.

    Examples:

        # Use Groww provider (default, no token needed for demo)
        bhav run strategies/my_strategy.py --start 2025-01-16 --end 2025-01-17

        # Use Upstox provider
        bhav run strategies/my_strategy.py --start 2025-01-16 --end 2025-01-17 \\
          --broker upstox --upstox-token YOUR_TOKEN

        # Use local CSV provider
        bhav run strategies/my_strategy.py --start 2025-01-16 --end 2025-01-17 \\
          --broker csv --csv-dir ./historical_data
    """
    # Validate inputs
    if broker not in ("groww", "upstox", "csv"):
        raise typer.BadParameter("--broker must be 'groww', 'upstox', or 'csv'")

    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    if start_date > end_date:
        raise typer.BadParameter(f"--start {start} is after --end {end}")

    if not strategy_path.exists():
        raise typer.BadParameter(f"Strategy file not found: {strategy_path}")

    # Load strategy
    strat = _load_strategy(strategy_path)
    resolved_lot = lot_size or default_lot_size(underlying)

    # Create provider
    console.print(f"[dim]Using provider:[/dim] [bold]{broker}[/bold]")
    provider = _create_provider(broker, groww_token, upstox_token, csv_dir)

    try:
        # Create reader (with optional cache)
        cache = ParquetCache(cache_dir) if cache_dir else None
        reader = DataReader(provider, cache)

        # Create resolver
        resolver = InstrumentResolver(provider, underlying)

        # Configure and run engine
        cfg = EngineConfig(
            underlying_key=underlying,
            start=start_date,
            end=end_date,
            starting_capital=capital,
            lot_size=resolved_lot,
            warmup_days=warmup_days,
        )

        console.print(
            f"[bold]Running[/bold] {strat.name} from {start} to {end} "
            f"(underlying={underlying}, lot={resolved_lot}, broker={broker})..."
        )

        engine = BarEngine(cfg, reader, resolver)
        portfolio = engine.run(strat)

        # Compute and display metrics
        metrics = compute_metrics(portfolio)
        run_id = f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"
        writer = ResultWriter(out_dir)
        path = writer.write(
            run_id,
            portfolio,
            metrics,
            strategy_name=strat.name,
            config={
                "start": start,
                "end": end,
                "capital": capital,
                "lot_size": resolved_lot,
                "broker": broker,
                "underlying": underlying,
                "warmup_days": warmup_days,
            },
        )

        _print_summary(metrics)
        console.print(f"\n[dim]Results written to[/dim] [bold]{path}[/bold]")

    finally:
        # Clean up provider
        provider.close()


def _print_summary(m):
    """Print summary metrics table."""
    t = Table(title="Summary", show_header=False, border_style="dim")
    t.add_column("k", style="dim")
    t.add_column("v")
    t.add_row("Total return", f"{m.total_return_pct:+.2f}%")
    t.add_row("CAGR", f"{m.cagr_pct:+.2f}%")
    t.add_row("Sharpe", f"{m.sharpe:.2f}")
    t.add_row("Sortino", "inf (no losing bars)" if m.sortino is None else f"{m.sortino:.2f}")
    t.add_row("Max drawdown", f"{m.max_drawdown_pct:.2f}%")
    t.add_row("Trades", f"{m.total_trades} ({m.win_rate_pct:.1f}% win rate)")
    t.add_row("Profit factor", "inf (no losses)" if m.profit_factor is None else f"{m.profit_factor:.2f}")
    t.add_row("Total costs", f"Rs {m.total_costs:,.0f}")
    console.print(t)


if __name__ == "__main__":
    app()
