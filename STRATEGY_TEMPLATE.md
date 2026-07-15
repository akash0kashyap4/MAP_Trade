# Custom Strategy Template for RAGI BOT Bhav Engine

How to write a custom strategy for backtesting with the Bhav engine via RAGI BOT's `/api/backtest/custom` endpoint (or the **Custom Strategy** tab in the Backtest panel).

> The API described here is the **real** `bhav.engine.strategy` interface. Method
> names matter — `ctx.spot()` is a call, `ctx.buy_option(...)` opens a position.
> There is no `ctx.bar_index`, `ctx.day_open`, `ctx.entry_call`, or
> `ctx.square_off`.

## Minimal Strategy

```python
from bhav.engine.strategy import Strategy, Context

class MyFirstStrategy(Strategy):
    name = "MyFirstStrategy"          # shown in results

    def on_day_start(self, ctx: Context):
        # Runs on the first bar of each trading day. Good place to reset
        # per-day flags.
        self.entered = False

    def on_bar(self, ctx: Context):
        # Runs once per 1-minute candle. Buy the ATM call once per day.
        if not getattr(self, "entered", False):
            key = ctx.buy_option(option_type="CE", strike_offset=0, lots=1)
            if key:                    # None if it couldn't fill (no data / no cash)
                self.entered = True

    # No manual exit needed: the engine squares off every open position at
    # 15:15. To exit earlier, call ctx.close_all() or ctx.close(key).

# REQUIRED: expose an instance named `strategy`.
strategy = MyFirstStrategy()
```

## The Context object

`ctx` is passed to every lifecycle hook. Its real surface:

| Member | Kind | Meaning |
|--------|------|---------|
| `ctx.spot()` | method → float | Current index price (close of the current bar). |
| `ctx.date` | attr (`datetime.date`) | Current trading date. |
| `ctx.bar` | attr (`Bar`) | Current candle: `.timestamp .open .high .low .close .volume .oi`. |
| `ctx.lot_size` | attr (int) | Contracts per lot for the underlying. |
| `ctx.portfolio` | attr (`Portfolio`) | Live positions/cash: `ctx.portfolio.cash`, `ctx.portfolio.positions` (dict). |
| `ctx.buy_option(...)` | method → key\|None | Open a long option. Returns the instrument key, or None if it couldn't fill. |
| `ctx.sell_option(...)` | method → key\|None | Open a short option (same args as buy). |
| `ctx.close(key, reason="manual")` | method | Close one position by its instrument key. |
| `ctx.close_all(reason="square_off")` | method | Close every open position. |

### `buy_option` / `sell_option` signature

```python
ctx.buy_option(
    option_type="CE",   # "CE" (call) or "PE" (put)   [required]
    strike_offset=0,    # in ATM steps: 0 = ATM, +1 = one step OTM, -1 = one step ITM
    lots=1,             # multiplied by ctx.lot_size to get quantity
    expiry=None,        # datetime.date; None = nearest available expiry
)
```

Returns the option's `instrument_key` (a string) on success, or `None` when the
order can't be placed — no expiry available, no candle data for that contract,
or not enough cash for the premium. **Always check the return value.**

There is **no** built-in `target_pct` / `sl_pct`. Exits happen either from the
engine's automatic 15:15 square-off, or by your code calling `ctx.close(...)` /
`ctx.close_all(...)`. Implement stops/targets yourself in `on_bar` if you want
them (compare the option's current price to your entry).

### Lifecycle hooks (all optional except `on_bar`)

```python
def on_start(self, ctx):      ...  # once, on the very first bar of the backtest
def on_day_start(self, ctx):  ...  # first bar of each trading day
def on_bar(self, ctx):        ...  # every 1-minute bar   (REQUIRED)
def on_day_end(self, ctx):    ...  # after the last bar of each day
def on_end(self, ctx):        ...  # once, at the end of the backtest
```

## Example: Momentum breakout

```python
from bhav.engine.strategy import Strategy, Context

class MomentumBreakout(Strategy):
    name = "MomentumBreakout"

    def on_day_start(self, ctx: Context):
        self.day_open = ctx.spot()
        self.entered = False

    def on_bar(self, ctx: Context):
        if self.entered:
            return
        if ctx.spot() > self.day_open * 1.003:      # 0.3% above the open
            if ctx.buy_option(option_type="CE", strike_offset=0, lots=1):
                self.entered = True

strategy = MomentumBreakout()
```

## Example: Mean reversion

```python
from bhav.engine.strategy import Strategy, Context

class MeanReversion(Strategy):
    name = "MeanReversion"

    def on_day_start(self, ctx: Context):
        self.day_open = ctx.spot()
        self.entered = False

    def on_bar(self, ctx: Context):
        if self.entered:
            return
        if ctx.spot() < self.day_open * 0.995:      # 0.5% below the open
            if ctx.buy_option(option_type="PE", strike_offset=0, lots=1):
                self.entered = True

strategy = MeanReversion()
```

## Example: manual stop-loss / target

```python
from bhav.engine.strategy import Strategy, Context

class BracketedCE(Strategy):
    name = "BracketedCE"

    def on_day_start(self, ctx: Context):
        self.key = None
        self.entry = None

    def on_bar(self, ctx: Context):
        if self.key is None:
            self.key = ctx.buy_option(option_type="CE", strike_offset=0, lots=1)
            if self.key:
                # look up the fill price from the open position
                self.entry = ctx.portfolio.positions[self.key].avg_price
            return
        # manage the open position
        pos = ctx.portfolio.positions.get(self.key)
        if pos is None:                     # already closed (e.g. 15:15 square-off)
            self.key = None
            return
        px = ctx.reader.option_bars(self.key, ctx.date)          # current option candles
        # (simplest: reuse the engine's own price lookup)
        last = Context._price_at(px, ctx.bar.timestamp)
        if last is None:
            return
        if last >= self.entry * 1.5 or last <= self.entry * 0.7:  # +50% target / -30% stop
            ctx.close(self.key, reason="bracket")
            self.key = None

strategy = BracketedCE()
```

## Submitting a backtest

### Custom Strategy tab (recommended)

Backtest panel → **Custom Strategy** tab → paste code → pick a broker and dates →
**RUN CUSTOM**. Results (win rate, Sharpe, P&L, equity sparkline, trade log)
render inline.

### API

The endpoint is **authenticated + same-origin** (it executes your Python, so it
is treated like any other operator action). Call it from the logged-in
dashboard session:

```bash
# submit
curl -X POST http://localhost:8000/api/backtest/custom \
  -H "Content-Type: application/json" \
  --cookie "ragi_session=<your session cookie>" \
  -d '{
    "strategy_code": "from bhav.engine.strategy import Strategy, Context\nclass S(Strategy):\n  name=\"S\"\n  def on_day_start(self,ctx): self.e=False\n  def on_bar(self,ctx):\n    if not self.e and ctx.buy_option(option_type=\"CE\"): self.e=True\nstrategy=S()",
    "start_date": "2025-01-16",
    "end_date": "2025-01-31",
    "underlying": "NSE_INDEX|Nifty 50",
    "capital": 500000,
    "broker": "csv",
    "csv_dir": "./historical_data"
  }'

# poll
curl --cookie "ragi_session=<...>" http://localhost:8000/api/backtest/custom/status
```

### Status / result shape

```json
{
  "running": false,
  "progress": 100,
  "result": {
    "strategy": "MyFirstStrategy",
    "total_trades": 5,
    "wins": 3,
    "losses": 2,
    "win_rate": 60.0,
    "total_pnl": 2500.50,
    "profit_factor": 2.15,
    "sharpe_ratio": 1.42,
    "max_drawdown": 1200.0,          // rupees
    "cagr": 45.2,
    "instrument": "NSE_INDEX|Nifty 50",
    "start_date": "2025-01-16",
    "end_date": "2025-01-31",
    "trades": [
      {"entry_time": "...", "entry_price": 125.5, "exit_time": "...",
       "exit_price": 188.2, "pnl": 625.0, "quantity": 65, "reason": "eod_square_off"}
    ]
  },
  "error": null
}
```

## Providers (`broker`)

| Value | Data source | Notes |
|-------|-------------|-------|
| `groww` (default) | Groww / yfinance spot + Black-Scholes synthetic options | Needs the live bot env (credentials). |
| `csv` | Local Parquet/CSV under `csv_dir` (`spot/` + `options/`) | Fully offline & deterministic. Requires `csv_dir`. |
| `upstox` | Upstox client | **Not bundled** in this build; selecting it returns a clear BrokerError. |

Historical option **chains** aren't available from Groww/CSV, so the resolver
synthesizes the requested contract on demand (key format
`"<underlying>|<expiry>|<strike>|<CE/PE>"`); the provider then serves synthetic
(Black-Scholes) or file-backed candles for it.

## Common pitfalls

1. **Missing `strategy = ...`** — the module must define a `strategy` variable.
2. **Calling `ctx.spot` without `()`** — it's a method, not an attribute.
3. **Assuming `bar_index`/`day_open`/`entry_call`/`square_off`** — none exist; use the table above.
4. **Ignoring the `buy_option` return value** — it's `None` when the order didn't fill.
5. **Heavy work in `on_bar`** — it runs ~375×/day; keep it light.
6. **Only stdlib + `bhav`** is importable inside strategy code.
