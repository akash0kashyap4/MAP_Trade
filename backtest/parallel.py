from __future__ import annotations
import itertools
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Optional

import pandas as pd

from backtest.engine import BacktestEngine


def _run_one(args: tuple) -> dict:
    instrument, start_str, end_str, config = args
    engine = BacktestEngine(use_ai_brain=False)
    try:
        result = engine.run(instrument, start_str, end_str, config)
        return {
            "config": config,
            "total_trades": result.total_trades,
            "win_rate": result.win_rate,
            "total_pnl": result.total_pnl,
            "profit_factor": result.profit_factor,
            "sharpe_ratio": result.sharpe_ratio,
            "max_drawdown": result.max_drawdown,
        }
    except Exception as e:
        return {"config": config, "error": str(e)}


def run_variants(
    instrument: str,
    start_str: str,
    end_str: str,
    param_grid: Optional[dict] = None,
    n_jobs: int = 4,
) -> pd.DataFrame:
    if param_grid is None:
        param_grid = {
            "stop_loss_rs":  [300, 500, 700],
            "target_rs":     [600, 1000, 1400],
            "lots":          [1],
        }

    keys   = list(param_grid.keys())
    values = list(param_grid.values())
    combos = list(itertools.product(*values))

    configs = []
    for combo in combos:
        cfg = dict(zip(keys, combo))
        configs.append((instrument, start_str, end_str, cfg))

    print(f"[parallel] Running {len(configs)} variants with {n_jobs} workers …")

    rows = []
    with ProcessPoolExecutor(max_workers=n_jobs) as pool:
        futures = {pool.submit(_run_one, c): c for c in configs}
        done = 0
        for future in as_completed(futures):
            done += 1
            row = future.result()
            rows.append(row)
            print(f"  [{done}/{len(configs)}] {row.get('config')} -> "
                  f"WR={row.get('win_rate',0):.1f}%  PnL=₹{row.get('total_pnl',0):,.0f}  "
                  f"Sharpe={row.get('sharpe_ratio',0):.2f}")

    df = pd.DataFrame(rows)
    if "sharpe_ratio" in df.columns:
        df = df.sort_values("sharpe_ratio", ascending=False).reset_index(drop=True)
    return df
