"""Backtest Orchestrator: Bridge between RAGI BOT API and Bhav engine.

Accepts strategy code, parameters, and broker selection, then:
1. Compiles user strategy code into a Strategy object
2. Selects appropriate data provider (Groww, Upstox, CSV)
3. Runs Bhav engine with provider
4. Formats results for dashboard
"""
from __future__ import annotations

import importlib.util
import logging
from datetime import date as date_type
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional

from bhav.data.cache import ParquetCache
from bhav.data.instruments import InstrumentResolver
from bhav.data.provider import BrokerDataProvider
from bhav.data.providers.groww_provider import GrowwDataProvider
from bhav.data.providers.local_csv_provider import LocalCsvProvider
from bhav.data.providers.upstox_provider import UpstoxProvider
from bhav.data.reader import DataReader
from bhav.data.underlyings import default_lot_size
from bhav.engine.bar_engine import BarEngine, EngineConfig
from bhav.engine.strategy import Strategy
from bhav.metrics.report import compute_metrics

log = logging.getLogger("ragi.backtest_orchestrator")


class BacktestResult:
    """Formatted backtest result for API consumption."""

    def __init__(self, portfolio, metrics, config, strategy_name):
        self.portfolio = portfolio
        self.metrics = metrics
        self.config = config
        self.strategy_name = strategy_name

        self.total_trades = len(portfolio.trades)
        self.wins = sum(1 for t in portfolio.trades if t.pnl > 0)
        self.losses = sum(1 for t in portfolio.trades if t.pnl < 0)
        self.win_rate = round(self.wins / max(self.total_trades, 1) * 100, 1)
        self.total_pnl = round(sum(t.pnl for t in portfolio.trades), 2)
        self.profit_factor = round(
            sum(t.pnl for t in portfolio.trades if t.pnl > 0)
            / max(sum(abs(t.pnl) for t in portfolio.trades if t.pnl < 0), 0.01),
            2,
        )
        self.sharpe_ratio = metrics.sharpe
        self.max_drawdown = round(metrics.max_drawdown_pct, 2)
        self.cagr = round(metrics.cagr_pct, 2)
        self.trades = [
            {
                "entry_time": str(t.entry_time),
                "entry_price": t.entry_price,
                "exit_time": str(t.exit_time),
                "exit_price": t.exit_price,
                "pnl": round(t.pnl, 2),
                "quantity": t.quantity,
            }
            for t in portfolio.trades[-30:]
        ]


def _compile_strategy_code(code: str) -> Strategy:
    """Compile user strategy code and return instantiated Strategy object.

    User code must define a `strategy` variable of type Strategy.

    Args:
        code: Python code as string

    Returns:
        Strategy instance

    Raises:
        ValueError: If code doesn't define `strategy` or has syntax errors
    """
    # Create temporary module
    spec = importlib.util.spec_from_loader("user_strategy", loader=None)
    if spec is None:
        raise ValueError("Could not create module spec")

    mod = importlib.util.module_from_spec(spec)
    try:
        exec(code, mod.__dict__)
    except SyntaxError as e:
        raise ValueError(f"Syntax error in strategy code: {e}")
    except Exception as e:
        raise ValueError(f"Error executing strategy code: {e}")

    if not hasattr(mod, "strategy"):
        raise ValueError("Strategy code must define a `strategy` variable")

    strategy = getattr(mod, "strategy")
    if not isinstance(strategy, Strategy):
        raise ValueError(f"strategy must be a Strategy instance, got {type(strategy)}")

    return strategy


def _create_provider(
    broker: str,
    groww_token: Optional[str] = None,
    upstox_token: Optional[str] = None,
    csv_dir: Optional[Path] = None,
) -> BrokerDataProvider:
    """Create data provider based on broker selection.

    Args:
        broker: "groww", "upstox", or "csv"
        groww_token: Groww API token (optional for demo)
        upstox_token: Upstox API token (required if broker=upstox)
        csv_dir: Directory for CSV provider (required if broker=csv)

    Returns:
        BrokerDataProvider instance

    Raises:
        ValueError: If broker invalid or required tokens missing
    """
    if broker == "groww":
        return GrowwDataProvider(api_token=groww_token)
    elif broker == "upstox":
        if not upstox_token:
            raise ValueError("upstox_token required for broker=upstox")
        return UpstoxProvider(token=upstox_token)
    elif broker == "csv":
        if not csv_dir:
            raise ValueError("csv_dir required for broker=csv")
        return LocalCsvProvider(csv_dir)
    else:
        raise ValueError(f"Unknown broker: {broker}. Use 'groww', 'upstox', or 'csv'")


def run_backtest(
    strategy_code: str,
    start: str,
    end: str,
    underlying: str = "NSE_INDEX|Nifty 50",
    capital: float = 500_000,
    lot_size: Optional[int] = None,
    warmup_days: int = 0,
    broker: str = "groww",
    groww_token: Optional[str] = None,
    upstox_token: Optional[str] = None,
    csv_dir: Optional[Path] = None,
    cache_dir: Optional[Path] = None,
) -> BacktestResult:
    """Run backtest with user strategy code.

    Args:
        strategy_code: Python code defining `strategy = MyStrategy()`
        start: Start date (YYYY-MM-DD)
        end: End date (YYYY-MM-DD)
        underlying: Symbol (e.g., "NSE_INDEX|Nifty 50")
        capital: Starting capital in Rs
        lot_size: Contract lot size (auto-lookup if None)
        warmup_days: Trading days to feed before start (no trades)
        broker: "groww", "upstox", or "csv"
        groww_token: Groww API token
        upstox_token: Upstox API token
        csv_dir: CSV data directory
        cache_dir: Candle cache directory

    Returns:
        BacktestResult with metrics and trades

    Raises:
        ValueError: If strategy code invalid, dates invalid, etc.
    """
    # Compile strategy
    log.info(f"Compiling strategy code ({len(strategy_code)} bytes)...")
    strategy = _compile_strategy_code(strategy_code)
    log.info(f"Strategy compiled: {strategy.name}")

    # Parse dates
    try:
        start_date = date_type.fromisoformat(start)
        end_date = date_type.fromisoformat(end)
    except ValueError as e:
        raise ValueError(f"Invalid date format (use YYYY-MM-DD): {e}")

    if start_date > end_date:
        raise ValueError(f"start_date {start} after end_date {end}")

    # Resolve lot size
    resolved_lot = lot_size or default_lot_size(underlying)
    log.info(f"Using lot size: {resolved_lot} for {underlying}")

    # Create provider
    log.info(f"Creating {broker} data provider...")
    provider = _create_provider(broker, groww_token, upstox_token, csv_dir)

    try:
        # Create reader (with optional cache)
        cache = ParquetCache(cache_dir) if cache_dir else None
        reader = DataReader(provider, cache)
        resolver = InstrumentResolver(provider, underlying)

        # Configure engine
        cfg = EngineConfig(
            underlying_key=underlying,
            start=start_date,
            end=end_date,
            starting_capital=capital,
            lot_size=resolved_lot,
            warmup_days=warmup_days,
        )

        log.info(
            f"Running {strategy.name} from {start} to {end} "
            f"(underlying={underlying}, capital={capital}, broker={broker})..."
        )

        # Run engine
        engine = BarEngine(cfg, reader, resolver)
        portfolio = engine.run(strategy)

        # Compute metrics
        metrics = compute_metrics(portfolio)

        # Format result
        result = BacktestResult(
            portfolio=portfolio,
            metrics=metrics,
            config={
                "start": start,
                "end": end,
                "capital": capital,
                "lot_size": resolved_lot,
                "broker": broker,
                "underlying": underlying,
                "warmup_days": warmup_days,
            },
            strategy_name=strategy.name,
        )

        log.info(f"Backtest complete: {result.total_trades} trades, {result.win_rate}% win rate, ₹{result.total_pnl} P&L")
        return result

    finally:
        provider.close()


def run_backtest_async(
    strategy_code: str,
    start: str,
    end: str,
    underlying: str = "NSE_INDEX|Nifty 50",
    capital: float = 500_000,
    lot_size: Optional[int] = None,
    warmup_days: int = 0,
    broker: str = "groww",
    groww_token: Optional[str] = None,
    upstox_token: Optional[str] = None,
    csv_dir: Optional[Path] = None,
    cache_dir: Optional[Path] = None,
) -> dict:
    """Wrapper for run_backtest that returns dict format for async API.

    Returns dict with keys: total_trades, wins, losses, win_rate, total_pnl,
    profit_factor, sharpe_ratio, max_drawdown, cagr, strategy, config, trades.
    """
    result = run_backtest(
        strategy_code=strategy_code,
        start=start,
        end=end,
        underlying=underlying,
        capital=capital,
        lot_size=lot_size,
        warmup_days=warmup_days,
        broker=broker,
        groww_token=groww_token,
        upstox_token=upstox_token,
        csv_dir=csv_dir,
        cache_dir=cache_dir,
    )

    return {
        "strategy": result.strategy_name,
        "total_trades": result.total_trades,
        "wins": result.wins,
        "losses": result.losses,
        "win_rate": result.win_rate,
        "total_pnl": result.total_pnl,
        "profit_factor": result.profit_factor if result.profit_factor != float("inf") else 999,
        "sharpe_ratio": result.sharpe_ratio,
        "max_drawdown": result.max_drawdown,
        "cagr": result.cagr,
        "instrument": result.config["underlying"],
        "start_date": result.config["start"],
        "end_date": result.config["end"],
        "config": result.config,
        "trades": result.trades,
    }
