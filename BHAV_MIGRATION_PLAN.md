# Bhav + Groww Migration Plan: Architecture & Implementation

**Status:** Design & Implementation Plan  
**Date:** 2026-07-15  
**Target:** Replace Upstox with Groww as primary data provider for bhav backtesting engine  

---

## 1. Current Dependency Analysis

### 1.1 Bhav Architecture (Current State)

**Tightly Coupled to Upstox:**
```
bhav/data/upstox_client.py          ← Core dependency
├─ UpstoxClient class               ← HTTP client + token auth
├─ 4 REST endpoints:
│  ├─ GET /v2/historical-candle     (spot/index candles)
│  ├─ GET /v2/expired-instruments/expiries  (past expiry dates)
│  ├─ GET /v2/expired-instruments/option/contract  (option chain)
│  └─ GET /v2/expired-instruments/historical-candle (option candles)
└─ OptionContract dataclass

bhav/data/reader.py                 ← DataReader uses UpstoxClient
├─ spot_bars()   → client.get_index_candles()
└─ option_bars() → client.get_expired_option_candles()

bhav/data/instruments.py            ← InstrumentResolver uses UpstoxClient
├─ expiries()     → client.get_expired_expiries()
├─ _chain()       → client.get_expired_contracts()
└─ resolve()      (strike lookup, ATM logic)

bhav/engine/bar_engine.py           ← Core engine (provider-agnostic)
├─ BarEngine class
├─ Uses reader.spot_bars()
├─ Uses reader.option_bars()
└─ Uses resolver.resolve()
```

**Provider-Agnostic Core:**
```
bhav/engine/
├─ bar_engine.py          ← Per-day 1-minute event loop (pure logic)
├─ strategy.py            ← User strategy interface
├─ portfolio.py           ← Position tracking + P&L
└─ costs.py               ← Indian cost model (brokerage, taxes, etc.)
```

### 1.2 RAGI BOT Current Integration

**Existing Groww Layer:**
- `groww/historical.py` provides alternative implementation with:
  - Groww API + yfinance fallback (spot candles)
  - Black-Scholes synthetic option candles
  - Expiry calculation (hardcoded weekly on Thu/Fri)
  - Mock option chain fallback

**Problem:** RAGI BOT's backtest engine copies logic from bhav but:
- Has incomplete Groww integration (synthetic options only)
- No direct use of bhav library
- Duplicated cost model logic
- Separate instrument resolver

---

## 2. Proposed Architecture

### 2.1 New Design Philosophy

```
┌─────────────────────────────────────────────────────────────────┐
│                    RAGI BOT (Orchestrator)                      │
│  ├─ Prompt parsing → Strategy file generation                   │
│  ├─ Parameter selection                                         │
│  └─ Results summarization                                       │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                   Bhav Backtesting Engine                        │
│  ├─ BarEngine (provider-agnostic event loop)                    │
│  ├─ Strategy interface                                          │
│  ├─ Portfolio + P&L tracking                                    │
│  └─ Cost models                                                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│              Data Provider Abstraction Layer                     │
│  ├─ BrokerDataProvider (interface)                              │
│  ├─ GrowwDataProvider (implementation)                          │
│  ├─ FallbackDataProvider (yfinance + synthetic)                 │
│  └─ LocalCacheDataProvider (CSV/Parquet fallback)               │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                   External Data Sources                          │
│  ├─ Groww API (live auth)                                       │
│  ├─ yfinance (free, limited history)                            │
│  ├─ Local cache (Parquet/CSV)                                   │
│  └─ Historical datasets                                         │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Key Interfaces (Broker Abstraction)

#### Interface 1: BrokerDataProvider (Core Contract)
```python
# bhav/data/provider.py

from abc import ABC, abstractmethod
from datetime import date
from dataclasses import dataclass

@dataclass(frozen=True)
class OptionContract:
    instrument_key: str
    strike: int
    option_type: str  # "CE" or "PE"
    expiry: date

class BrokerDataProvider(ABC):
    """Contract for any broker/data provider."""
    
    @abstractmethod
    def get_spot_candles(
        self, 
        instrument_key: str, 
        d: date, 
        interval: str = "1minute"
    ) -> list:
        """Fetch spot/index candles for one day.
        
        Returns: [[timestamp, open, high, low, close, volume, oi], ...]
        """
        pass
    
    @abstractmethod
    def get_option_candles(
        self, 
        option_key: str, 
        d: date, 
        interval: str = "1minute"
    ) -> list:
        """Fetch option candles for one day.
        
        Can be real historical or synthetic (Black-Scholes).
        """
        pass
    
    @abstractmethod
    def get_expiries(self, underlying_key: str) -> list[date]:
        """Return sorted list of all past expiry dates."""
        pass
    
    @abstractmethod
    def get_option_chain(
        self, 
        underlying_key: str, 
        expiry: date
    ) -> list[OptionContract]:
        """Return all contracts (CE + PE, all strikes) for one expiry."""
        pass
    
    def close(self) -> None:
        """Optional cleanup."""
        pass
```

#### Interface 2: InstrumentMetadata (Broker Config)
```python
# bhav/data/metadata.py

from dataclasses import dataclass

@dataclass(frozen=True)
class InstrumentMetadata:
    """Broker-specific config for an instrument."""
    
    instrument_key: str      # e.g., "NSE_INDEX|Nifty 50"
    atm_step: int            # e.g., 100 for NIFTY
    lot_size: int            # e.g., 25 for NIFTY
    option_expiry_weekday: int  # 0=Mon...6=Sun; 3=Thu, 4=Fri
```

#### Interface 3: DataReader (Engine's data access layer)
```python
# bhav/data/reader.py (refactored)

from bhav.data.provider import BrokerDataProvider
from bhav.data.cache import DataCache

class DataReader:
    """Hides provider selection from engine. Handles caching."""
    
    def __init__(
        self, 
        provider: BrokerDataProvider,
        cache: DataCache | None = None
    ):
        self.provider = provider
        self.cache = cache
    
    def spot_bars(self, instrument_key: str, d: date, interval: str = "1minute"):
        """Read spot candles with cache-aware fallback."""
        if self.cache and self.cache.has(instrument_key, interval, d):
            return self.cache.read(instrument_key, interval, d)
        bars = self.provider.get_spot_candles(instrument_key, d, interval)
        if self.cache and bars:
            self.cache.write(instrument_key, interval, d, bars)
        return bars
    
    def option_bars(self, option_key: str, d: date, interval: str = "1minute"):
        """Read option candles with cache-aware fallback."""
        if self.cache and self.cache.has(option_key, interval, d):
            return self.cache.read(option_key, interval, d)
        bars = self.provider.get_option_candles(option_key, d, interval)
        if self.cache and bars:
            self.cache.write(option_key, interval, d, bars)
        return bars
    
    def expiries(self, underlying_key: str) -> list[date]:
        return self.provider.get_expiries(underlying_key)
    
    def option_chain(self, underlying_key: str, expiry: date) -> list[OptionContract]:
        return self.provider.get_option_chain(underlying_key, expiry)
```

### 2.3 Folder Structure (Post-Migration)

```
bhav/
├── data/
│   ├── provider.py              ← NEW: BrokerDataProvider interface
│   ├── metadata.py              ← NEW: InstrumentMetadata dataclass
│   ├── reader.py                ← REFACTORED: Use provider instead of client
│   ├── instruments.py           ← REFACTORED: Remove client dependency
│   ├── cache.py                 ← EXISTING: Works with provider
│   ├── calendar.py              ← EXISTING: NSE trading days
│   ├── underlyings.py           ← EXISTING: Lot size, ATM step lookup
│   │
│   └── providers/                ← NEW: Implementations of BrokerDataProvider
│       ├── __init__.py
│       ├── groww_provider.py    ← NEW: Groww + yfinance
│       ├── upstox_provider.py   ← REFACTORED: Wraps old UpstoxClient
│       └── local_csv_provider.py ← NEW: Fallback for stored datasets
│
├── engine/
│   ├── bar_engine.py            ← EXISTING: No changes needed
│   ├── strategy.py              ← EXISTING: No changes needed
│   ├── portfolio.py             ← EXISTING: No changes needed
│   └── costs.py                 ← EXISTING: No changes needed
│
├── metrics/
│   └── report.py                ← EXISTING: No changes needed
│
└── cli.py                        ← REFACTORED: Wire up providers
```

---

## 3. Migration Steps

### Phase 1: Create Abstraction Layer (Non-Breaking)

**Step 1a:** Create `BrokerDataProvider` interface
- File: `bhav/data/provider.py`
- Defines abstract contract
- No breaking changes

**Step 1b:** Create `GrowwDataProvider` implementation
- File: `bhav/data/providers/groww_provider.py`
- Integrates existing `groww/historical.py` logic
- Includes yfinance fallback
- Includes synthetic option candles (Black-Scholes)

**Step 1c:** Create `UpstoxProvider` wrapper (backward compatibility)
- File: `bhav/data/providers/upstox_provider.py`
- Wraps existing `UpstoxClient`
- Implements `BrokerDataProvider` interface

**Step 1d:** Create `LocalCsvProvider` (fallback)
- File: `bhav/data/providers/local_csv_provider.py`
- Reads pre-stored parquet/CSV files
- No API dependency

### Phase 2: Refactor DataReader & InstrumentResolver

**Step 2a:** Refactor `DataReader`
- Replace `UpstoxClient` parameter with `BrokerDataProvider`
- Keep cache logic unchanged
- All spot/option candle access goes through provider

**Step 2b:** Refactor `InstrumentResolver`
- Replace `UpstoxClient` with `BrokerDataProvider`
- expiry lookup → provider.get_expiries()
- chain lookup → provider.get_option_chain()
- Keep strike resolution logic unchanged

### Phase 3: Update CLI & Entry Points

**Step 3a:** Update `cli.py`
- Add `--provider` flag (default: "groww")
- Add provider-specific options (e.g., --groww-token, --csv-path)
- Wire up provider instantiation

**Step 3b:** Create `bhav/api/providers.py`
- Factory function to create provider from config
- Handle environment variables for tokens/paths

### Phase 4: Integration with RAGI BOT

**Step 4a:** Replace RAGI BOT's backtest engine
- Use bhav's BarEngine directly
- Remove duplicated logic

**Step 4b:** Wire Groww credentials
- RAGI BOT reads from `groww/auth.py`
- Passes to GrowwDataProvider

---

## 4. Interface Definitions (Complete)

### 4.1 BrokerDataProvider

```python
# bhav/data/provider.py

from abc import ABC, abstractmethod
from datetime import date
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class OptionContract:
    instrument_key: str
    strike: int
    option_type: str  # "CE" or "PE"
    expiry: date
    # Future fields: implied_vol, delta, open_interest, etc.

class BrokerDataProvider(ABC):
    """Abstract interface for any historical data provider.
    
    Implementations: Groww, Upstox, yfinance, local CSV, etc.
    
    Contract:
    - All methods return data in normalized format (list of lists)
    - Timestamps in ISO format (YYYY-MM-DDTHH:MM:SS+05:30)
    - Prices as floats, volumes as ints
    - Return empty list on "no data" (not None)
    - All exceptions wrapped in BrokerError
    """
    
    @abstractmethod
    def get_spot_candles(
        self,
        instrument_key: str,
        d: date,
        interval: str = "1minute",
    ) -> list[list]:
        """Fetch OHLCV for spot/index on one trading day.
        
        Args:
            instrument_key: e.g., "NSE_INDEX|Nifty 50"
            d: Date to fetch
            interval: "1minute", "5minute", "1hour", etc.
        
        Returns:
            [[timestamp, open, high, low, close, volume, oi], ...]
            Empty list if no data available.
        """
        pass
    
    @abstractmethod
    def get_option_candles(
        self,
        option_key: str,
        d: date,
        interval: str = "1minute",
    ) -> list[list]:
        """Fetch OHLCV for one option contract on one trading day.
        
        Args:
            option_key: Broker-specific format (see below)
            d: Date to fetch
            interval: "1minute", "5minute", "1hour", etc.
        
        Returns:
            [[timestamp, open, high, low, close, volume, oi], ...]
            Empty list if no data or synthetic unavailable.
        
        Notes:
            - Can be real historical (preferred) or synthetic (Black-Scholes)
            - Upstox format: "NSE_FO|Nifty50-01Jan2025-24000CE"
            - Groww format: "NSE_FO|Nifty50|2025-01-01|24000|CE" (normalized)
        """
        pass
    
    @abstractmethod
    def get_expiries(self, underlying_key: str) -> list[date]:
        """Return list of all past expiry dates for an underlying.
        
        Args:
            underlying_key: e.g., "NSE_INDEX|Nifty 50"
        
        Returns:
            Sorted list of date objects (oldest first)
        """
        pass
    
    @abstractmethod
    def get_option_chain(
        self,
        underlying_key: str,
        expiry: date,
    ) -> list[OptionContract]:
        """Return all option contracts for one expiry.
        
        Args:
            underlying_key: e.g., "NSE_INDEX|Nifty 50"
            expiry: Expiry date
        
        Returns:
            List of OptionContract (CE + PE, all strikes)
            Empty list if expiry not available.
        """
        pass
    
    def close(self) -> None:
        """Optional cleanup (close HTTP connections, etc.)."""
        pass
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()
```

### 4.2 GrowwDataProvider

```python
# bhav/data/providers/groww_provider.py

from datetime import date
from bhav.data.provider import BrokerDataProvider, OptionContract
from groww.historical import (
    get_index_candles,
    get_expired_option_candles,
    get_expired_expiries,
    get_expired_option_key,
)
from groww.auth import get_groww_client

class GrowwDataProvider(BrokerDataProvider):
    """Groww API + yfinance fallback for backtesting.
    
    Features:
    - Real spot candles from Groww (via yfinance on fallback)
    - Synthetic option candles (Black-Scholes)
    - Automatic yfinance fallback for historical data
    """
    
    def __init__(self, api_token: str | None = None):
        """
        Args:
            api_token: Optional Groww OAuth token.
                      If None, uses groww.auth.get_groww_client().
        """
        self.api_token = api_token
        # Client lazy-init on first use
        self._groww_client = None
    
    def _get_groww_client(self):
        if self._groww_client is None:
            if self.api_token:
                # Create authenticated client with token
                from groww.auth import GroWWClient
                self._groww_client = GroWWClient(token=self.api_token)
            else:
                # Use default authenticated session
                self._groww_client = get_groww_client()
        return self._groww_client
    
    def get_spot_candles(
        self,
        instrument_key: str,
        d: date,
        interval: str = "1minute",
    ) -> list[list]:
        """Fetch spot candles via Groww → yfinance fallback."""
        date_str = d.strftime("%Y-%m-%d")
        return get_index_candles(instrument_key, date_str)
    
    def get_option_candles(
        self,
        option_key: str,
        d: date,
        interval: str = "1minute",
    ) -> list[list]:
        """Synthetic option candles via Black-Scholes."""
        date_str = d.strftime("%Y-%m-%d")
        # option_key format: "NSE_INDEX|Nifty 50|2025-01-16|24000|CE"
        return get_expired_option_candles(option_key, date_str)
    
    def get_expiries(self, underlying_key: str) -> list[date]:
        """Fetch past expiry dates."""
        raw_strings = get_expired_expiries(underlying_key)
        return [date.fromisoformat(x) for x in raw_strings]
    
    def get_option_chain(
        self,
        underlying_key: str,
        expiry: date,
    ) -> list[OptionContract]:
        """Fetch option chain for one expiry.
        
        Note: Groww historical API may not have direct chain endpoint.
        Fallback: Construct from cached synthetic options or mock data.
        """
        # TODO: Implement once Groww historical chain endpoint is confirmed
        # For now, return empty (engine will use synthetic candles)
        return []
    
    def close(self) -> None:
        # No persistent connection in Groww API (stateless HTTP)
        pass
```

### 4.3 LocalCsvProvider (Fallback)

```python
# bhav/data/providers/local_csv_provider.py

from datetime import date
from pathlib import Path
import polars as pl
from bhav.data.provider import BrokerDataProvider, OptionContract

class LocalCsvProvider(BrokerDataProvider):
    """Load pre-stored candles from local Parquet/CSV files.
    
    Folder structure expected:
        data/
        ├── spot/
        │   ├── NSE_INDEX_Nifty50_2025-01-16.parquet
        │   └── ...
        └── options/
            ├── NSE_FO_Nifty50_2025-01-16_24000_CE_2025-01-30.parquet
            └── ...
    """
    
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.spot_dir = self.data_dir / "spot"
        self.opt_dir = self.data_dir / "options"
    
    def get_spot_candles(
        self,
        instrument_key: str,
        d: date,
        interval: str = "1minute",
    ) -> list[list]:
        date_str = d.strftime("%Y-%m-%d")
        safe_key = instrument_key.replace("|", "_").replace(" ", "")
        filename = f"{safe_key}_{date_str}.parquet"
        path = self.spot_dir / filename
        
        if not path.exists():
            return []
        
        df = pl.read_parquet(path)
        return df.to_dicts()  # or df.rows() depending on polars version
    
    def get_option_candles(
        self,
        option_key: str,
        d: date,
        interval: str = "1minute",
    ) -> list[list]:
        # option_key: "NSE_INDEX|Nifty 50|2025-01-16|24000|CE"
        parts = option_key.split("|")
        # ... similar logic to spot_candles
        return []
    
    def get_expiries(self, underlying_key: str) -> list[date]:
        # Scan available files, infer expiries
        return []
    
    def get_option_chain(
        self,
        underlying_key: str,
        expiry: date,
    ) -> list[OptionContract]:
        return []
```

---

## 5. Code Skeleton: GrowwDataProvider (Full Implementation)

### 5.1 Minimal Working Example

```python
# bhav/data/providers/groww_provider.py

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from bhav.data.provider import BrokerDataProvider, OptionContract

if TYPE_CHECKING:
    from groww.auth import GroWWClient


class GrowwDataProvider(BrokerDataProvider):
    """Groww API + yfinance + Black-Scholes for backtesting.
    
    Design:
    1. Spot candles: Groww API → yfinance (1m, 5m, 1h, daily)
    2. Option candles: Black-Scholes synthetic (no real API)
    3. Expiry dates: Hardcoded NSE weekly schedule
    4. Option chain: Mock (future: Groww chain API if available)
    """
    
    def __init__(self, api_token: str | None = None, cache_dir: str | None = None):
        """Initialize Groww provider.
        
        Args:
            api_token: Optional Groww OAuth token. If None, uses env/session auth.
            cache_dir: Optional directory for caching candles locally.
        """
        self.api_token = api_token
        self.cache_dir = cache_dir
        self._groww_client: GroWWClient | None = None
    
    def _get_client(self) -> GroWWClient:
        """Lazy-init Groww client."""
        if self._groww_client is None:
            from groww.auth import get_groww_client
            self._groww_client = get_groww_client()
        return self._groww_client
    
    def get_spot_candles(
        self,
        instrument_key: str,
        d: date,
        interval: str = "1minute",
    ) -> list[list]:
        """Fetch spot candles from Groww or yfinance.
        
        Falls back: Groww → yfinance
        """
        from groww.historical import get_index_candles
        date_str = d.strftime("%Y-%m-%d")
        return get_index_candles(instrument_key, date_str)
    
    def get_option_candles(
        self,
        option_key: str,
        d: date,
        interval: str = "1minute",
    ) -> list[list]:
        """Generate synthetic option candles via Black-Scholes.
        
        Format: "NSE_INDEX|Nifty 50|2025-01-16|24000|CE"
        """
        from groww.historical import get_expired_option_candles
        date_str = d.strftime("%Y-%m-%d")
        return get_expired_option_candles(option_key, date_str)
    
    def get_expiries(self, underlying_key: str) -> list[date]:
        """Return sorted list of all past weekly expiries.
        
        Implementation:
        - NSE: Every Thursday (3)
        - BSE: Every Friday (4)
        """
        from groww.historical import get_expired_expiries
        raw_strings = get_expired_expiries(underlying_key)
        return sorted([date.fromisoformat(x) for x in raw_strings])
    
    def get_option_chain(
        self,
        underlying_key: str,
        expiry: date,
    ) -> list[OptionContract]:
        """Return all option contracts for one expiry.
        
        **Limitation:** Groww doesn't provide direct historical option chain.
        
        Options:
        1. Empty list (engine uses synthetic candles for resolution)
        2. Call Groww live chain API (current data, not historical)
        3. Fall back to ATM-only (hardcode available strikes)
        
        For now: Return empty list. Engine handles via synthetic candles.
        """
        return []
    
    def close(self) -> None:
        """No-op for HTTP stateless client."""
        pass


# Example usage:
if __name__ == "__main__":
    from datetime import date
    
    provider = GrowwDataProvider()
    
    # Fetch spot
    candles = provider.get_spot_candles(
        "NSE_INDEX|Nifty 50",
        date(2025, 1, 16),
    )
    print(f"Spot candles: {len(candles)} bars")
    
    # Fetch option candles (synthetic)
    opt_candles = provider.get_option_candles(
        "NSE_INDEX|Nifty 50|2025-01-16|24000|CE",
        date(2025, 1, 16),
    )
    print(f"Option candles: {len(opt_candles)} bars")
    
    # Fetch expiries
    expiries = provider.get_expiries("NSE_INDEX|Nifty 50")
    print(f"Expiries: {len(expiries)} past dates")
    
    provider.close()
```

---

## 6. RAGI BOT Integration Flow

### 6.1 User → Strategy → Backtest

```
┌─ User Input (Natural Language) ────────────────────────────┐
│  "Test straddle selling strategy on NIFTY, Jan 16-17"     │
└────────────────────────────────────────────────────────────┘
                              ↓
┌─ RAGI BOT: Claude + Prompt Parsing ────────────────────────┐
│  1. Parse intent → strategy type, parameters                │
│  2. Generate Python strategy file                           │
│  3. Write to disk: strategies/user_straddle_jan.py          │
└────────────────────────────────────────────────────────────┘
                              ↓
┌─ Backtest Orchestration (RAGI BOT) ────────────────────────┐
│  1. Select broker: "groww" (default)                        │
│  2. Configure: capital=500k, start=2025-01-16, end=2025-01-17
│  3. Instantiate GrowwDataProvider                           │
│  4. Instantiate ParquetCache (optional)                     │
│  5. Instantiate DataReader(provider, cache)                 │
│  6. Instantiate InstrumentResolver(provider)                │
│  7. Instantiate BarEngine(config, reader, resolver)         │
└────────────────────────────────────────────────────────────┘
                              ↓
┌─ Execute Backtest (Bhav Engine) ───────────────────────────┐
│  1. Load strategy from file                                 │
│  2. engine.run(strategy) → Portfolio result                 │
│  3. Metrics: sharpe, max_dd, win_rate, etc.                 │
└────────────────────────────────────────────────────────────┘
                              ↓
┌─ Results → RAGI BOT Dashboard ─────────────────────────────┐
│  1. Parse metrics from Portfolio                            │
│  2. Generate summary (P&L, trades, stats)                   │
│  3. Return to user in dashboard UI                          │
└────────────────────────────────────────────────────────────┘
```

### 6.2 Code Flow (RAGI BOT Integration)

```python
# ragi_bot/backtest_orchestrator.py

from datetime import date
from pathlib import Path
from typing import Optional

from bhav.data.providers.groww_provider import GrowwDataProvider
from bhav.data.reader import DataReader
from bhav.data.cache import ParquetCache
from bhav.data.instruments import InstrumentResolver
from bhav.engine.bar_engine import BarEngine, EngineConfig
from bhav.engine.strategy import Strategy


def run_backtest(
    strategy_path: Path,
    underlying: str = "NSE_INDEX|Nifty 50",
    start_date: date = None,
    end_date: date = None,
    capital: float = 500_000.0,
    lot_size: int | None = None,
    broker: str = "groww",
    groww_token: str | None = None,
    cache_dir: Path | None = None,
) -> dict:
    """Run a backtest and return metrics.
    
    Args:
        strategy_path: Path to user strategy file (contains strategy variable)
        underlying: Instrument key
        start_date, end_date: Backtest period
        capital: Starting capital
        lot_size: Override auto-lookup
        broker: "groww", "upstox", or "csv"
        groww_token: Groww API token (optional)
        cache_dir: Directory for caching candles
    
    Returns:
        {
            "total_trades": int,
            "wins": int,
            "losses": int,
            "win_rate": float,
            "total_pnl": float,
            "max_drawdown": float,
            "sharpe_ratio": float,
            "trades": [...],
            ...
        }
    """
    
    # 1. Load strategy
    strategy = _load_strategy(strategy_path)
    
    # 2. Instantiate data provider
    if broker == "groww":
        provider = GrowwDataProvider(api_token=groww_token)
    elif broker == "upstox":
        from bhav.data.providers.upstox_provider import UpstoxProvider
        provider = UpstoxProvider(token=groww_token)  # Reuse param name
    else:
        raise ValueError(f"Unknown broker: {broker}")
    
    # 3. Optional cache
    cache = None
    if cache_dir:
        cache = ParquetCache(cache_dir)
    
    # 4. Create reader & resolver
    reader = DataReader(provider, cache)
    resolver = InstrumentResolver(provider, underlying)
    
    # 5. Configure engine
    cfg = EngineConfig(
        underlying_key=underlying,
        start=start_date or date.today(),
        end=end_date or date.today(),
        starting_capital=capital,
        lot_size=lot_size,
    )
    
    # 6. Run backtest
    engine = BarEngine(cfg, reader, resolver)
    portfolio = engine.run(strategy)
    
    # 7. Compute metrics & return
    metrics = compute_backtest_metrics(portfolio)
    
    provider.close()
    return metrics


def _load_strategy(path: Path) -> Strategy:
    """Dynamically load strategy from Python file."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("user_strategy", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load strategy from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "strategy"):
        raise ValueError(f"{path} must expose a `strategy` variable")
    return mod.strategy


def compute_backtest_metrics(portfolio) -> dict:
    """Extract P&L metrics from portfolio object."""
    from bhav.metrics.report import compute_metrics
    return compute_metrics(portfolio)
```

### 6.3 CLI Entry Point (bhav integration)

```python
# bhav/cli.py (refactored)

import typer
from pathlib import Path
from datetime import date

app = typer.Typer(help="Bhav: NSE options backtester")

@app.command()
def run(
    strategy_path: Path = typer.Argument(...),
    start: str = typer.Option(..., help="YYYY-MM-DD"),
    end: str = typer.Option(..., help="YYYY-MM-DD"),
    broker: str = typer.Option("groww", help="Data provider: groww, upstox, csv"),
    underlying: str = typer.Option("NSE_INDEX|Nifty 50"),
    capital: float = typer.Option(500_000.0),
    lot_size: int = typer.Option(0, help="0 = auto-lookup"),
    groww_token: str = typer.Option(None, envvar="GROWW_TOKEN"),
    upstox_token: str = typer.Option(None, envvar="UPSTOX_TOKEN"),
    csv_path: Path = typer.Option(None, help="For broker=csv"),
    cache_dir: Path = typer.Option(Path("cache")),
    out_dir: Path = typer.Option(Path("runs")),
):
    """Run backtest with specified broker."""
    
    strat = _load_strategy(strategy_path)
    token = groww_token if broker == "groww" else upstox_token
    
    cfg = EngineConfig(
        underlying_key=underlying,
        start=date.fromisoformat(start),
        end=date.fromisoformat(end),
        starting_capital=capital,
        lot_size=lot_size or None,
    )
    
    # Select provider
    if broker == "groww":
        from bhav.data.providers.groww_provider import GrowwDataProvider
        provider = GrowwDataProvider(api_token=groww_token)
    elif broker == "upstox":
        from bhav.data.providers.upstox_provider import UpstoxProvider
        provider = UpstoxProvider(token=upstox_token)
    elif broker == "csv":
        from bhav.data.providers.local_csv_provider import LocalCsvProvider
        provider = LocalCsvProvider(csv_path or Path("data"))
    else:
        raise typer.BadParameter(f"Unknown broker: {broker}")
    
    cache = ParquetCache(cache_dir) if cache_dir else None
    reader = DataReader(provider, cache)
    resolver = InstrumentResolver(provider, underlying)
    engine = BarEngine(cfg, reader, resolver)
    
    portfolio = engine.run(strat)
    
    # Write results
    run_id = _write_results(portfolio, out_dir)
    typer.echo(f"Backtest complete: {run_id}")
```

---

## 7. Fallback Strategy (If Groww Historical Options Data Insufficient)

### 7.1 Problem Statement

Groww may lack complete historical option candles for:
- Expired contracts (>expiry date)
- Old expiries (>1 month back)
- Some strikes or less-liquid options

### 7.2 Fallback Hierarchy

```
┌─ Tier 1: Real Data ────────────────────────────────┐
│  1. Groww historical option candles (if available)  │
│  2. Groww expired-instruments API (if available)    │
└───────────────────────────────────────────────────┘
                      ↓ (if missing)
┌─ Tier 2: Synthetic Data ──────────────────────────┐
│  1. Black-Scholes synthetic candles (from spot)     │
│  2. Fixed IV, spot-dependent                        │
└───────────────────────────────────────────────────┘
                      ↓ (if no spot)
┌─ Tier 3: Mock Data ───────────────────────────────┐
│  1. Hardcoded mock candles (1m, 5m)                 │
│  2. Spot price + realistic noise                    │
└───────────────────────────────────────────────────┘
```

### 7.3 Implementation in GrowwDataProvider

```python
# bhav/data/providers/groww_provider.py

class GrowwDataProvider(BrokerDataProvider):
    
    def get_option_candles(
        self,
        option_key: str,
        d: date,
        interval: str = "1minute",
    ) -> list[list]:
        """Fetch or synthesize option candles with fallback."""
        
        # Tier 1: Real data from Groww API
        try:
            candles = self._fetch_real_option_candles(option_key, d, interval)
            if candles:
                return candles
        except Exception as e:
            print(f"[GrowwDataProvider] Tier 1 (real) failed: {e}")
        
        # Tier 2: Synthetic via Black-Scholes
        try:
            candles = self._synthesize_option_candles(option_key, d, interval)
            if candles:
                return candles
        except Exception as e:
            print(f"[GrowwDataProvider] Tier 2 (synthetic) failed: {e}")
        
        # Tier 3: Mock data
        try:
            candles = self._mock_option_candles(option_key, d, interval)
            if candles:
                return candles
        except Exception as e:
            print(f"[GrowwDataProvider] Tier 3 (mock) failed: {e}")
        
        # Fallback: empty
        return []
    
    def _fetch_real_option_candles(self, option_key: str, d: date, interval: str):
        """Try Groww historical option candles."""
        from groww.historical import get_expired_option_candles
        date_str = d.strftime("%Y-%m-%d")
        return get_expired_option_candles(option_key, date_str)
    
    def _synthesize_option_candles(self, option_key: str, d: date, interval: str):
        """Generate via Black-Scholes from spot."""
        # Parse option_key: "NSE_INDEX|Nifty 50|2025-01-16|24000|CE"
        parts = option_key.split("|")
        if len(parts) != 5:
            return []
        
        instrument_key = "|".join(parts[:2])
        expiry_str = parts[2]
        strike = int(parts[3])
        option_type = parts[4]
        
        # Fetch spot candles
        spot_candles = self.get_spot_candles(instrument_key, d, interval)
        if not spot_candles:
            return []
        
        # Synthesize
        from groww.historical import _synthetic_option_candles_from_spot
        expiry = date.fromisoformat(expiry_str)
        return _synthetic_option_candles_from_spot(
            spot_candles, expiry_str, strike, option_type, d.strftime("%Y-%m-%d")
        )
    
    def _mock_option_candles(self, option_key: str, d: date, interval: str):
        """Generate mock candles for testing/demo."""
        # Simple mock: ATM option with realistic premium decay
        parts = option_key.split("|")
        if len(parts) != 5:
            return []
        
        strike = int(parts[3])
        option_type = parts[4]
        
        # Assume spot is near strike (ATM)
        base_premium = strike * 0.02  # 2% of strike as ATM premium
        
        # Generate 6.5 hour worth of 1-minute candles
        import datetime
        start_time = datetime.datetime.combine(d, datetime.time(9, 15))
        candles = []
        
        for i in range(390):  # 9:15 to 15:30
            ts = (start_time + datetime.timedelta(minutes=i)).isoformat()
            # Decay premium over time
            decay = 1.0 - (i / 390.0) * 0.3  # 30% decay over day
            premium = base_premium * decay
            noise = premium * 0.05 * (i % 3 - 1)  # ±5% noise
            
            o = premium + noise
            c = premium - noise / 2
            h = max(o, c) * 1.01
            l = min(o, c) * 0.99
            
            candles.append([ts, o, h, l, c, 0, 0])
        
        return candles
```

---

## 8. API Flow: RAGI BOT ↔ Bhav

### 8.1 Request/Response Flow

```
RAGI BOT Frontend
      ↓
API Endpoint: POST /api/backtest
      ↓
{
  "strategy_code": "class MyStrategy(Strategy): ...",
  "parameters": {
    "underlying": "NSE_INDEX|Nifty 50",
    "start_date": "2025-01-16",
    "end_date": "2025-01-17",
    "capital": 500000,
    "lot_size": 25
  }
}
      ↓
Orchestrator:
  1. Save strategy to file
  2. Import & validate
  3. Select GrowwDataProvider
  4. Configure BarEngine
  5. engine.run(strategy)
      ↓
Portfolio (Bhav)
  trades: [...],
  pnl: {...},
  positions: {...}
      ↓
Metrics Calculation
  win_rate, sharpe, max_dd, etc.
      ↓
API Response: 200 OK
{
  "run_id": "run-20250115-abc123",
  "status": "complete",
  "metrics": {
    "total_trades": 15,
    "wins": 10,
    "losses": 5,
    "win_rate": 0.667,
    "total_pnl": 45000.0,
    "max_drawdown": -5000.0,
    "sharpe_ratio": 1.23
  },
  "trades": [
    {
      "entry": "2025-01-16T09:15:00",
      "exit": "2025-01-16T10:30:00",
      "side": "BUY",
      "quantity": 25,
      "entry_price": 145.5,
      "exit_price": 150.0,
      "pnl": 1125.0
    },
    ...
  ]
}
```

### 8.2 Module Dependency Map

```
ragi_bot/backtest.py
├── imports: bhav.engine.bar_engine.BarEngine
├── imports: bhav.data.reader.DataReader
├── imports: bhav.data.instruments.InstrumentResolver
├── imports: bhav.data.providers.groww_provider.GrowwDataProvider
├── imports: bhav.metrics.report.compute_metrics
└── imports: groww.auth.get_groww_client

bhav/engine/bar_engine.py (NO CHANGES)
├── uses: bhav.data.reader.DataReader
├── uses: bhav.data.instruments.InstrumentResolver
└── uses: bhav.engine.portfolio.Portfolio

bhav/data/reader.py (REFACTORED)
├── depends on: bhav.data.provider.BrokerDataProvider (interface)
├── uses: bhav.data.cache.ParquetCache (optional)
└── replaces: bhav.data.upstox_client.UpstoxClient

bhav/data/instruments.py (REFACTORED)
├── depends on: bhav.data.provider.BrokerDataProvider (interface)
└── replaces: bhav.data.upstox_client.UpstoxClient

bhav/data/providers/groww_provider.py (NEW)
├── implements: bhav.data.provider.BrokerDataProvider
├── uses: groww.historical.* (from RAGI BOT)
└── delegates to: Black-Scholes, yfinance
```

---

## 9. Risks, Assumptions & Limitations

### 9.1 Key Assumptions

| Assumption | Rationale | Fallback |
|------------|-----------|----------|
| Groww API won't change contracts | Minimize version conflicts | Wrap in compat layer + versioning |
| yfinance 1m available within 7d | Free data source | Use 5m candles + interpolate |
| Black-Scholes sufficient for options | No better free model | Add support for real historical later |
| NSE calendar stable (no new holidays) | Public domain, published yearly | Config file for custom holidays |
| Upstox token not required after migration | Clean break from legacy | Keep UpstoxProvider as plugin |

### 9.2 Known Limitations

**Groww API:**
- No real historical option candles endpoint
- Option chain access may require subscription
- Rate limits on free tier (~100 req/min)
- yfinance 1m limited to 7 days back

**Black-Scholes Synthetic Candles:**
- Fixed IV (0.15) not realistic
- No skew/smile modeling
- Ignores bid-ask spreads
- May give false signals on wide OTM options

**Solution:** Combine with local CSV fallback for production backtests.

### 9.3 Migration Risks

| Risk | Severity | Mitigation |
|------|----------|-----------|
| Regression in backtests (different prices) | High | Parallel backtest: Upstox vs Groww on same date |
| Groww auth token expiry | Medium | Automatic re-auth via OAuth flow |
| yfinance rate-limiting | Medium | Cache aggressively, use 5m on older data |
| Synthetic options mispricing | High | Backtest sensitivity analysis, compare to live pricing |
| Data inconsistency (spot vs option) | Medium | Validate candle timestamps match, log mismatches |

### 9.4 Testing Strategy

```python
# tests/test_provider_consistency.py

def test_groww_vs_upstox_spot_prices():
    """Run same backtest on both providers, compare P&L."""
    # Both should be within 2% of each other
    pass

def test_black_scholes_vs_real_options():
    """Compare synthetic vs real option candles (if available)."""
    pass

def test_cache_persistence():
    """Verify caching works across backtests."""
    pass

def test_fallback_hierarchy():
    """Ensure fallback tiers work correctly."""
    pass
```

---

## 10. Implementation Checklist

### Phase 1: Abstraction (Week 1)
- [ ] Create `bhav/data/provider.py` (BrokerDataProvider interface)
- [ ] Create `bhav/data/metadata.py` (InstrumentMetadata)
- [ ] Create `bhav/data/providers/__init__.py`
- [ ] Create `bhav/data/providers/groww_provider.py`
- [ ] Create `bhav/data/providers/upstox_provider.py` (wrapper)
- [ ] Create `bhav/data/providers/local_csv_provider.py`
- [ ] Unit tests for each provider

### Phase 2: Refactor Existing Modules (Week 2)
- [ ] Refactor `bhav/data/reader.py` (use provider instead of UpstoxClient)
- [ ] Refactor `bhav/data/instruments.py` (use provider instead of UpstoxClient)
- [ ] Update `bhav/cli.py` (add --provider flag)
- [ ] Integration tests

### Phase 3: RAGI BOT Integration (Week 3)
- [ ] Create `ragi_bot/backtest_orchestrator.py`
- [ ] Create API endpoint `/api/backtest`
- [ ] Create API endpoint `/api/backtest/{run_id}` (results)
- [ ] Wire up strategy file generation
- [ ] Wire up Groww auth in orchestrator

### Phase 4: Testing & Polish (Week 4)
- [ ] Regression testing (Groww vs Upstox vs cached data)
- [ ] Load testing (yfinance rate limits)
- [ ] Dashboard integration
- [ ] Documentation

---

## 11. Conclusion

This migration preserves bhav's core strength (the pure backtesting engine) while making it modular and broker-agnostic. By introducing `BrokerDataProvider` as the sole entry point for external data, we:

1. ✅ Remove Upstox coupling
2. ✅ Enable Groww (+ fallbacks) cleanly
3. ✅ Allow future brokers (Shoonya, Zebu, etc.) without refactoring
4. ✅ Keep the engine production-friendly
5. ✅ Simplify RAGI BOT's orchestration layer

The fallback hierarchy ensures backtests never fail silently—they gracefully degrade from real data → synthetic → mock, with clear logging at each step.

