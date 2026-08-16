"""Vectorized quick-backtester. Pure pandas, works on any yfinance symbol.

For deep options/intraday work use backtest/engine.py — this is for
strategy R&D on EOD data (SMA cross, RSI mean-reversion, momentum).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _load(symbol: str, period: str, interval: str) -> pd.DataFrame:
    import yfinance as yf
    df = yf.Ticker(symbol).history(period=period, interval=interval)
    if df.empty:
        raise RuntimeError(f"no data for {symbol}")
    df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    return df


def _signal_sma_cross(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> pd.Series:
    f = df["close"].rolling(fast).mean()
    s = df["close"].rolling(slow).mean()
    return (f > s).astype(int)  # 1 = long, 0 = flat


def _signal_rsi_meanrev(df: pd.DataFrame, length: int = 14, buy: int = 30, sell: int = 55) -> pd.Series:
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(length).mean()
    loss = -delta.clip(upper=0).rolling(length).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    out = []
    holding = 0
    for r in rsi:
        if pd.isna(r):
            out.append(0)
            continue
        if holding == 0 and r < buy:
            holding = 1
        elif holding == 1 and r > sell:
            holding = 0
        out.append(holding)
    return pd.Series(out, index=df.index)


def _signal_momentum(df: pd.DataFrame, lookback: int = 60) -> pd.Series:
    ret = df["close"].pct_change(lookback)
    return (ret > 0).astype(int)


STRATEGIES = {
    "sma_cross": _signal_sma_cross,
    "rsi_meanrev": _signal_rsi_meanrev,
    "momentum": _signal_momentum,
}


def _metrics(equity: pd.Series, trades: int) -> dict:
    if equity.empty:
        return {}
    rets = equity.pct_change().dropna()
    if rets.empty or rets.std() == 0:
        sharpe = 0.0
    else:
        sharpe = float(rets.mean() / rets.std() * np.sqrt(252))
    dd = (equity / equity.cummax() - 1).min()
    total = equity.iloc[-1] / equity.iloc[0] - 1
    yrs = max(len(equity) / 252, 1e-9)
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / yrs) - 1
    return {
        "total_return_pct": round(total * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "sharpe": round(sharpe, 2),
        "max_drawdown_pct": round(dd * 100, 2),
        "trades": int(trades),
        "bars": int(len(equity)),
    }


def run_backtest(
    symbol: str,
    strategy: str = "sma_cross",
    period: str = "5y",
    interval: str = "1d",
    cost_bps: float = 5.0,
    **params,
) -> dict:
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy}; pick {list(STRATEGIES)}")
    df = _load(symbol, period, interval)
    pos = STRATEGIES[strategy](df, **params).fillna(0)
    ret = df["close"].pct_change().fillna(0)
    strat_ret = pos.shift(1).fillna(0) * ret
    changes = pos.diff().abs().fillna(0)
    strat_ret -= changes * (cost_bps / 10_000)
    equity = (1 + strat_ret).cumprod()
    bh = (1 + ret).cumprod()
    return {
        "symbol": symbol,
        "strategy": strategy,
        "params": params,
        "period": period,
        "interval": interval,
        "cost_bps": cost_bps,
        "strategy_metrics": _metrics(equity, int(changes.sum())),
        "buyhold_metrics": _metrics(bh, 1),
    }


def compare_strategies(symbol: str, **kwargs) -> list[dict]:
    return [run_backtest(symbol, s, **kwargs) for s in STRATEGIES]
