# Custom Strategy Template for RAGI BOT Bhav Engine

This document shows how to write a custom strategy for backtesting with the Bhav engine via RAGI BOT's `/api/backtest/custom` endpoint.

## Minimal Strategy Example

```python
from bhav.engine.strategy import Strategy, Context

class MyFirstStrategy(Strategy):
    """A simple buy-on-day-open strategy."""
    
    def __init__(self):
        self.name = "MyFirstStrategy"
        self.entry_bar = None
    
    def on_start(self, ctx: Context):
        """Called once before trading begins."""
        pass
    
    def on_bar(self, ctx: Context):
        """Called for each 1-minute candle."""
        # Example: Buy on the first bar of each day, hold for 10 bars
        if ctx.bar_index == 0:  # First bar of the day
            # ctx.entry_call(strike_offset=0, option_type="CE")
            pass
    
    def on_day_end(self, ctx: Context):
        """Called at end of trading day (after 15:30 IST)."""
        # Square off any open positions at close
        # ctx.square_off()
        pass
    
    def on_end(self, ctx: Context):
        """Called after all trading days are complete."""
        pass

# Must define this variable pointing to your strategy instance
strategy = MyFirstStrategy()
```

## Context Object (Available in on_bar, on_day_end, on_end)

The `ctx: Context` object provides access to market data and trading functions:

```python
# Market Data
ctx.date              # Current date (datetime.date)
ctx.bar_time          # Current bar time as HH:MM string
ctx.bar_index         # Index of bar within current day (0, 1, 2, ...)
ctx.spot_price        # Current spot price (float)
ctx.day_open          # Spot price at day open
ctx.day_high          # Highest spot price today
ctx.day_low           # Lowest spot price today

# Portfolio State
ctx.cash              # Available cash (Rs)
ctx.total_equity      # Portfolio value (cash + positions)
ctx.positions         # List of open positions

# Trading Functions
ctx.entry_call(strike_offset=0, option_type="CE", target_pct=1.0, sl_pct=0.5)
# Open a position: 
#   strike_offset: ±N steps from ATM (e.g., 0=ATM, 1=+100 pts, -1=-100 pts)
#   option_type: "CE" or "PE"
#   target_pct: profit target (1.0 = +100%)
#   sl_pct: stop loss (0.5 = -50%)

ctx.exit_position(contract_key)
# Close a specific position by key

ctx.square_off()
# Close all open positions at current market price
```

## Trading Rules

1. **Entry**: Call `ctx.entry_call()` with strike offset and option type
2. **Exit**: Positions auto-exit on SL/target or can be manually closed
3. **Position Limit**: Strategy respects portfolio capital and lot size
4. **Cost Model**: Brokerage (~40 Rs per trade), taxes included in P&L

## Example Strategy: Momentum Breakout

```python
from bhav.engine.strategy import Strategy, Context

class MomentumBreakout(Strategy):
    """Buy on breakout above yesterday's high."""
    
    def __init__(self):
        self.name = "MomentumBreakout"
        self.prev_day_high = None
        self.has_entered = False
    
    def on_start(self, ctx: Context):
        self.prev_day_high = ctx.day_high
    
    def on_bar(self, ctx: Context):
        if self.has_entered:
            return  # Already in a position
        
        # Buy if spot breaks above previous day's high
        if ctx.spot_price > self.prev_day_high and ctx.bar_index < 300:
            ctx.entry_call(
                strike_offset=0,      # ATM
                option_type="CE",     # Call for bullish view
                target_pct=0.50,      # Exit at +50% profit
                sl_pct=0.20,          # Exit at -20% loss
            )
            self.has_entered = True
    
    def on_day_end(self, ctx: Context):
        # Store today's high for tomorrow's reference
        self.prev_day_high = ctx.day_high
        # Close any remaining positions at end of day
        ctx.square_off()
        self.has_entered = False
    
    def on_end(self, ctx: Context):
        pass

strategy = MomentumBreakout()
```

## Example Strategy: Mean Reversion (Lower Lows)

```python
from bhav.engine.strategy import Strategy, Context

class MeanReversion(Strategy):
    """Sell when spot makes lower lows (expect bounce)."""
    
    def __init__(self):
        self.name = "MeanReversion"
        self.day_low_seen = None
    
    def on_start(self, ctx: Context):
        self.day_low_seen = ctx.spot_price
    
    def on_bar(self, ctx: Context):
        # Update day low
        if ctx.spot_price < self.day_low_seen:
            self.day_low_seen = ctx.spot_price
        
        # Sell (Put) when spot breaks below day low (expect reversion up)
        if ctx.spot_price < self.day_low_seen * 0.995 and ctx.bar_index > 30:
            ctx.entry_call(
                strike_offset=0,      # ATM strike
                option_type="PE",     # Put for bearish view
                target_pct=1.0,       # Exit at +100% profit
                sl_pct=0.30,          # Exit at -30% loss
            )
    
    def on_day_end(self, ctx: Context):
        ctx.square_off()
        self.day_low_seen = ctx.spot_price
    
    def on_end(self, ctx: Context):
        pass

strategy = MeanReversion()
```

## Submitting Your Strategy

### 1. Via API (Recommended for Automation)

```bash
curl -X POST http://localhost:8000/api/backtest/custom \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_code": "from bhav.engine.strategy import Strategy, Context\nclass MyStrat(Strategy):\n  ...",
    "start_date": "2025-01-16",
    "end_date": "2025-01-31",
    "underlying": "NSE_INDEX|Nifty 50",
    "capital": 500000,
    "broker": "groww"
  }'
```

### 2. Via Dashboard (Recommended for Interactive Testing)

(Not yet implemented - coming in Phase 3.2)

## Response Format

After the backtest completes, check status via:

```bash
curl http://localhost:8000/api/backtest/custom/status
```

Response:
```json
{
  "running": false,
  "result": {
    "strategy": "MyFirstStrategy",
    "total_trades": 5,
    "wins": 3,
    "losses": 2,
    "win_rate": 60.0,
    "total_pnl": 2500.50,
    "profit_factor": 2.15,
    "sharpe_ratio": 1.42,
    "max_drawdown": 1200.0,
    "cagr": 45.2,
    "instrument": "NSE_INDEX|Nifty 50",
    "start_date": "2025-01-16",
    "end_date": "2025-01-31",
    "trades": [
      {
        "entry_time": "2025-01-16 09:40:00",
        "entry_price": 125.5,
        "exit_time": "2025-01-16 10:15:00",
        "exit_price": 188.2,
        "pnl": 625.00,
        "quantity": 75
      },
      ...
    ]
  },
  "error": null
}
```

## Provider Selection

The `broker` parameter selects the data source:

- **`"groww"`** (default): Live Groww API with Black-Scholes fallback for missing options
- **`"upstox"`**: Upstox API (legacy, requires token)
- **`"csv"`**: Offline CSV/Parquet files (for deterministic testing)

## Common Pitfalls

1. **Forgetting `strategy = ...` variable**: The code must define a `strategy` variable.
2. **Importing missing modules**: Only import from `bhav.engine.strategy` and standard library.
3. **Infinite loops in on_bar**: Keep logic lightweight — runs 390 times/day per symbol.
4. **Not closing positions**: Use `ctx.square_off()` in `on_day_end()` to avoid carrying risk overnight.
5. **Hardcoding dates**: Parameters like start/end are set via API, not in code.

## Tips for Better Backtests

1. **Test on 2-4 weeks of data** first to validate logic
2. **Use split test**: Run same strategy on 2025-01-01 to 2025-02-28 and 2025-03-01 to 2025-04-30 to check robustness
3. **Monitor Sharpe ratio**: Aim for >1.0 (>2.0 is excellent)
4. **Check profit factor**: Should be >1.5 for viable strategies (>2.0 is strong)
5. **Validate on different underlyings**: NIFTY, BANKNIFTY, SENSEX respond differently

## What's Next

Phase 3.2 will add:
- Dashboard UI for strategy code editor
- Parameter sweep (test SL% and target% combinations)
- Walk-forward analysis (daily retrain)
- Live paper trading hook

For now, use the API with `curl` or your favorite HTTP client.
