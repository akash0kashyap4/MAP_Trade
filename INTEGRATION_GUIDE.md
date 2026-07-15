# RAGI BOT + Bhav Integration Guide

This guide shows how to integrate the refactored Bhav backtesting engine with RAGI BOT.

## Quick Start

### 1. Import the Engine

```python
from bhav.data.providers.groww_provider import GrowwDataProvider
from bhav.data.reader import DataReader
from bhav.data.instruments import InstrumentResolver
from bhav.engine.bar_engine import BarEngine, EngineConfig
from datetime import date

# Create provider (Groww + yfinance fallback)
provider = GrowwDataProvider()

# Create reader (handles caching)
reader = DataReader(provider)

# Create resolver (strike lookup, expiry selection)
resolver = InstrumentResolver(provider, "NSE_INDEX|Nifty 50")

# Configure engine
cfg = EngineConfig(
    underlying_key="NSE_INDEX|Nifty 50",
    start=date(2025, 1, 16),
    end=date(2025, 1, 17),
    starting_capital=500_000,
)

# Create engine
engine = BarEngine(cfg, reader, resolver)

# Run backtest
portfolio = engine.run(your_strategy)

# Get metrics
from bhav.metrics.report import compute_metrics
metrics = compute_metrics(portfolio)
print(f"Win rate: {metrics['win_rate']:.2%}")
print(f"Total P&L: ${metrics['total_pnl']:,.2f}")
```

### 2. Create a User Strategy

```python
from bhav.engine.strategy import Strategy, Context

class FirstCandleDirection(Strategy):
    """Simple straddle-based strategy."""
    
    def on_start(self, ctx: Context) -> None:
        """Called once at start of backtest."""
        pass
    
    def on_bar(self, ctx: Context) -> None:
        """Called once per minute."""
        spot = ctx.current_bar.close
        
        if ctx.is_warmup:
            return
        
        if ctx.is_first_bar_of_day:
            # First bar: sell ATM straddle
            atm = ctx.resolver.atm_strike(spot)
            expiry = ctx.resolver.nearest_expiry(ctx.current_date)
            
            if expiry:
                # Sell call
                call_opt = ctx.resolver.resolve(expiry, atm, "CE")
                if call_opt:
                    ctx.short(call_opt.contract.instrument_key, 1)
                
                # Sell put
                put_opt = ctx.resolver.resolve(expiry, atm, "PE")
                if put_opt:
                    ctx.short(put_opt.contract.instrument_key, 1)
    
    def on_day_end(self, ctx: Context) -> None:
        """Called at end of each trading day."""
        # Positions auto-squared at 15:15

strategy = FirstCandleDirection()
```

### 3. Wire Up RAGI BOT API

```python
# ragi_bot/routers/backtest.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import date
from pathlib import Path

router = APIRouter(prefix="/api/backtest", tags=["backtest"])

class BacktestRequest(BaseModel):
    strategy_code: str  # Python code
    underlying: str = "NSE_INDEX|Nifty 50"
    start_date: str  # "2025-01-16"
    end_date: str    # "2025-01-17"
    capital: float = 500_000
    lot_size: int | None = None
    broker: str = "groww"  # or "upstox", "csv"

class BacktestResponse(BaseModel):
    run_id: str
    status: str
    metrics: dict
    trades: list

@router.post("", response_model=BacktestResponse)
async def run_backtest(req: BacktestRequest):
    """Run a backtest and return results."""
    try:
        # 1. Save strategy to temp file
        strat_file = Path(f"/tmp/strategy_{hash(req.strategy_code)}.py")
        strat_file.write_text(f"{req.strategy_code}\n")
        
        # 2. Load strategy
        from ragi_bot.backtest_orchestrator import _load_strategy
        strategy = _load_strategy(strat_file)
        
        # 3. Run backtest
        from bhav.data.providers.groww_provider import GrowwDataProvider
        from bhav.data.reader import DataReader
        from bhav.data.instruments import InstrumentResolver
        from bhav.engine.bar_engine import BarEngine, EngineConfig
        
        provider = GrowwDataProvider()
        reader = DataReader(provider)
        resolver = InstrumentResolver(provider, req.underlying)
        
        cfg = EngineConfig(
            underlying_key=req.underlying,
            start=date.fromisoformat(req.start_date),
            end=date.fromisoformat(req.end_date),
            starting_capital=req.capital,
            lot_size=req.lot_size,
        )
        
        engine = BarEngine(cfg, reader, resolver)
        portfolio = engine.run(strategy)
        
        # 4. Extract metrics
        from bhav.metrics.report import compute_metrics
        metrics = compute_metrics(portfolio)
        trades = _extract_trades(portfolio)
        
        provider.close()
        strat_file.unlink()
        
        # 5. Return
        run_id = f"run-{date.today()}-{hash(req.strategy_code) % 10000}"
        return BacktestResponse(
            run_id=run_id,
            status="complete",
            metrics=metrics,
            trades=trades,
        )
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

def _extract_trades(portfolio) -> list[dict]:
    """Convert portfolio trades to JSON."""
    # Implementation depends on Portfolio.trades structure
    return []
```

## Provider Selection

### Groww (Recommended)
- **Pros:** Free, no auth needed for demo, fallback to yfinance, synthetic options
- **Cons:** No historical option candles, yfinance limited to 7 days for 1m data
- **Usage:**
  ```python
  from bhav.data.providers.groww_provider import GrowwDataProvider
  provider = GrowwDataProvider()
  ```

### Upstox (Backward Compatibility)
- **Pros:** Real historical option candles, better accuracy
- **Cons:** Requires auth token, rate limits, daily token expiry
- **Usage:**
  ```python
  from bhav.data.providers.upstox_provider import UpstoxProvider
  provider = UpstoxProvider(token="YOUR_TOKEN")
  ```

### Local CSV (Offline)
- **Pros:** Deterministic, reproducible, offline
- **Cons:** Manual data preparation, limited coverage
- **Usage:**
  ```python
  from bhav.data.providers.local_csv_provider import LocalCsvProvider
  provider = LocalCsvProvider(data_dir="./data")
  ```

## Error Handling

All providers raise `BrokerError` on failures:

```python
from bhav.data.provider import BrokerError

try:
    provider = GrowwDataProvider()
    reader = DataReader(provider)
    engine = BarEngine(cfg, reader, resolver)
    portfolio = engine.run(strategy)
except BrokerError as e:
    print(f"Broker error: {e}")
    # Fallback to CSV provider?
    provider = LocalCsvProvider(data_dir="./fallback_data")
    # Retry...
```

## Caching

Optional: Cache candles locally to speed up repeated backtests:

```python
from bhav.data.cache import ParquetCache

cache = ParquetCache("./cache")
reader = DataReader(provider, cache)
```

First backtest fetches from API/yfinance, subsequent runs use cache.

## Testing

### Unit Test Template

```python
# tests/test_backtest_integration.py

from bhav.data.providers.groww_provider import GrowwDataProvider
from bhav.data.reader import DataReader
from bhav.data.instruments import InstrumentResolver
from bhav.engine.bar_engine import BarEngine, EngineConfig
from bhav.engine.strategy import Strategy, Context
from datetime import date

def test_backtest_runs():
    """Verify backtest executes without errors."""
    
    class DummyStrategy(Strategy):
        def on_bar(self, ctx: Context):
            pass
    
    provider = GrowwDataProvider()
    reader = DataReader(provider)
    resolver = InstrumentResolver(provider, "NSE_INDEX|Nifty 50")
    
    cfg = EngineConfig(
        underlying_key="NSE_INDEX|Nifty 50",
        start=date(2025, 1, 16),
        end=date(2025, 1, 16),
    )
    
    engine = BarEngine(cfg, reader, resolver)
    portfolio = engine.run(DummyStrategy())
    
    assert portfolio is not None
    provider.close()
```

### Integration Test Template

```python
def test_provider_consistency():
    """Verify Groww and CSV providers produce same results."""
    
    from bhav.data.providers.groww_provider import GrowwDataProvider
    from bhav.data.providers.local_csv_provider import LocalCsvProvider
    
    # Run same backtest on both providers
    for Provider in [GrowwDataProvider, LocalCsvProvider]:
        provider = Provider() if Provider == GrowwDataProvider else Provider("./data")
        # ... run backtest, assert results consistent
```

## Troubleshooting

### "yfinance returned empty"
- Age of data > 7 days and you need 1m candles?
- Solution: Use 5m candles or CSV provider with pre-loaded data
- yfinance limits: 1m (7d), 5m (60d), 1h (730d)

### "Groww token expired"
- OAuth tokens refresh daily around 03:30 IST
- Solution: Re-auth before backtest or use CSV provider

### "Option chain not available"
- Groww historical chain API not implemented yet
- Solution: Engine uses synthetic candles instead; still valid
- Strikes resolved via ATM logic + fallback offsets

### Performance is slow
- Enable caching:
  ```python
  cache = ParquetCache("./cache")
  reader = DataReader(provider, cache)
  ```
- Pre-warm cache before backtests:
  ```bash
  python scripts/warm_cache.py --start 2025-01-01 --end 2025-01-31
  ```

## Next Steps

1. **Clone bhav into RAGI BOT** (if not already done):
   ```bash
   git clone https://github.com/rajmaurya0904/bhav.git
   # or add as git submodule
   ```

2. **Update requirements.txt:**
   ```
   polars>=0.19
   yfinance
   groww-api  # Or your groww client
   ```

3. **Update RAGI BOT CLI:**
   ```bash
   # Old
   python -m backtest.engine --strategy ...
   
   # New
   bhav run strategies/my_strategy.py --start 2025-01-16 --end 2025-01-17
   ```

4. **Migrate strategies:**
   - Rewrite strategies to inherit from `bhav.engine.strategy.Strategy`
   - Use `ctx.resolver`, `ctx.portfolio` instead of old APIs

5. **A/B test results:**
   - Run same strategy on Groww vs CSV vs Upstox
   - Ensure P&L differences < 5% (due to synthetic candles)

