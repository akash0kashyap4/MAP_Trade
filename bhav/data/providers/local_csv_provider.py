"""Local CSV/Parquet provider for pre-stored historical data.

Useful for:
- Backtesting when APIs are down
- Deterministic, reproducible backtests
- Offline environments
- Bundled datasets (e.g., sample NSE data)
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from bhav.data.provider import BrokerDataProvider, BrokerError, OptionContract


class LocalCsvProvider(BrokerDataProvider):
    """Load pre-stored candles from local Parquet/CSV files.

    Expected folder structure:
        data/
        ├── spot/
        │   ├── NSE_INDEX_Nifty50_2025-01-16.parquet
        │   ├── NSE_INDEX_Nifty50_2025-01-17.parquet
        │   └── ...
        └── options/
            ├── NSE_FO_Nifty50_2025-01-16_24000_CE.parquet
            └── ...

    CSV files should have columns: timestamp, open, high, low, close, volume, oi
    """

    def __init__(self, data_dir: Path | str):
        """Initialize local provider.

        Args:
            data_dir: Root directory containing spot/ and options/ subdirs.
        """
        self.data_dir = Path(data_dir)
        self.spot_dir = self.data_dir / "spot"
        self.opt_dir = self.data_dir / "options"

        if not self.spot_dir.exists():
            self.spot_dir.mkdir(parents=True, exist_ok=True)
        if not self.opt_dir.exists():
            self.opt_dir.mkdir(parents=True, exist_ok=True)

    def get_spot_candles(
        self,
        instrument_key: str,
        d: date,
        interval: str = "1minute",
    ) -> list[list]:
        """Load spot candles from local storage."""
        try:
            date_str = d.strftime("%Y-%m-%d")
            safe_key = self._sanitize_filename(instrument_key)
            filename = f"{safe_key}_{date_str}.parquet"

            # Try parquet first
            path = self.spot_dir / filename
            if path.exists():
                return self._read_parquet(path)

            # Fall back to CSV
            csv_path = path.with_suffix(".csv")
            if csv_path.exists():
                return self._read_csv(csv_path)

            return []
        except Exception as e:
            raise BrokerError(
                f"Failed to load spot candles for {instrument_key} on {d}: {e}"
            ) from e

    def get_option_candles(
        self,
        option_key: str,
        d: date,
        interval: str = "1minute",
    ) -> list[list]:
        """Load option candles from local storage.

        option_key format: "NSE_INDEX|Nifty 50|2025-01-16|24000|CE"
        or Upstox format: "NSE_FO|Nifty50-01Jan2025-24000CE"
        """
        try:
            date_str = d.strftime("%Y-%m-%d")
            safe_key = self._sanitize_filename(option_key)
            filename = f"{safe_key}_{date_str}.parquet"

            path = self.opt_dir / filename
            if path.exists():
                return self._read_parquet(path)

            csv_path = path.with_suffix(".csv")
            if csv_path.exists():
                return self._read_csv(csv_path)

            return []
        except Exception as e:
            raise BrokerError(
                f"Failed to load option candles for {option_key} on {d}: {e}"
            ) from e

    def get_expiries(self, underlying_key: str) -> list[date]:
        """Infer available expiry dates by scanning filenames."""
        try:
            expiries_set = set()

            # Scan spot dir for dates
            for file in self.spot_dir.glob(f"*{self._sanitize_filename(underlying_key)}*.parquet"):
                # Extract date from filename
                parts = file.stem.split("_")
                if len(parts) >= 2:
                    try:
                        d = date.fromisoformat(parts[-1])
                        expiries_set.add(d)
                    except (ValueError, IndexError):
                        pass

            return sorted(list(expiries_set))
        except Exception as e:
            raise BrokerError(f"Failed to scan expiries for {underlying_key}: {e}") from e

    def get_option_chain(
        self,
        underlying_key: str,
        expiry: date,
    ) -> list[OptionContract]:
        """Infer option chain from available files.

        Scans for all strikes/types available on a given expiry date.
        """
        # For now: return empty. Could be enhanced by parsing filenames.
        return []

    @staticmethod
    def _sanitize_filename(key: str) -> str:
        """Convert instrument key to safe filename."""
        return key.replace("|", "_").replace(" ", "").replace("-", "_")

    @staticmethod
    def _read_parquet(path: Path) -> list[list]:
        """Read parquet file and return as list of lists."""
        try:
            import polars as pl

            df = pl.read_parquet(path)
            # Expected columns: timestamp, open, high, low, close, volume, oi
            return df.rows()
        except ImportError:
            raise BrokerError("polars not installed; cannot read parquet files")

    @staticmethod
    def _read_csv(path: Path) -> list[list]:
        """Read CSV file and return as list of lists."""
        try:
            import polars as pl

            df = pl.read_csv(path)
            return df.rows()
        except ImportError:
            raise BrokerError("polars not installed; cannot read CSV files")
