"""The practical free stack, wired end-to-end:

    yfinance (data) -> pandas-ta (indicators) -> Plotly / mplfinance (chart)
                                              -> Claude (analysis summary)

One call, one bundle back. Chart file paths + AI summary included.
Requires: yfinance, pandas-ta, plotly, mplfinance (all in requirements.txt).
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytz

IST = pytz.timezone("Asia/Kolkata")
CHART_DIR = Path(os.getenv("MAP_TRADE_CHART_DIR", "data/charts"))


def fetch_ohlcv(symbol: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
    """yfinance step."""
    import yfinance as yf
    df = yf.Ticker(symbol).history(period=period, interval=interval)
    if df.empty:
        raise RuntimeError(f"no data for {symbol}")
    df.columns = [c.lower() for c in df.columns]
    return df[["open", "high", "low", "close", "volume"]]


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """pandas-ta step — attaches the common set. Missing lib falls back to
    pandas rolling means so the pipeline still returns something usable."""
    out = df.copy()
    try:
        import pandas_ta as ta
        out["sma20"] = ta.sma(out["close"], length=20)
        out["sma50"] = ta.sma(out["close"], length=50)
        out["ema9"] = ta.ema(out["close"], length=9)
        out["rsi"] = ta.rsi(out["close"], length=14)
        macd = ta.macd(out["close"])
        if macd is not None:
            out = out.join(macd)
        bb = ta.bbands(out["close"], length=20)
        if bb is not None:
            out = out.join(bb)
        atr = ta.atr(out["high"], out["low"], out["close"], length=14)
        if atr is not None:
            out["atr"] = atr
    except ImportError:
        out["sma20"] = out["close"].rolling(20).mean()
        out["sma50"] = out["close"].rolling(50).mean()
        delta = out["close"].diff()
        up = delta.clip(lower=0).rolling(14).mean()
        dn = -delta.clip(upper=0).rolling(14).mean()
        out["rsi"] = 100 - 100 / (1 + up / dn.replace(0, pd.NA))
    return out


def _last_snapshot(df: pd.DataFrame) -> dict:
    row = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else row
    keep = ["close", "sma20", "sma50", "ema9", "rsi", "atr"]
    snap = {}
    for k in keep:
        if k in df.columns and pd.notna(row.get(k)):
            snap[k] = round(float(row[k]), 2)
    macd_col = next((c for c in df.columns if c.lower().startswith("macd_")), None)
    macds_col = next((c for c in df.columns if c.lower().startswith("macds_")), None)
    if macd_col and pd.notna(row.get(macd_col)):
        snap["macd"] = round(float(row[macd_col]), 3)
    if macds_col and pd.notna(row.get(macds_col)):
        snap["macd_signal"] = round(float(row[macds_col]), 3)
    snap["change_pct"] = round((float(row["close"]) / float(prev["close"]) - 1) * 100, 2)
    snap["period_high"] = round(float(df["high"].max()), 2)
    snap["period_low"] = round(float(df["low"].min()), 2)
    return snap


def render_plotly(df: pd.DataFrame, symbol: str, out_path: Path) -> Path:
    """Plotly interactive HTML — candles + SMAs + RSI subplot."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25],
        vertical_spacing=0.03, subplot_titles=(f"{symbol} — price", "RSI(14)"),
    )
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        name="OHLC",
    ), row=1, col=1)
    for col, color in [("sma20", "#2b8"), ("sma50", "#e83")]:
        if col in df.columns:
            fig.add_trace(go.Scatter(x=df.index, y=df[col], name=col.upper(),
                                     line=dict(width=1, color=color)), row=1, col=1)
    if "rsi" in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df["rsi"], name="RSI",
                                 line=dict(color="#69f")), row=2, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="#f66", row=2, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="#6f6", row=2, col=1)
    fig.update_layout(template="plotly_dark", xaxis_rangeslider_visible=False,
                      height=720, margin=dict(l=40, r=20, t=50, b=20))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(out_path), include_plotlyjs="cdn")
    return out_path


def render_mplfinance(df: pd.DataFrame, symbol: str, out_path: Path) -> Path:
    """mplfinance PNG — a static candle chart with SMAs + volume."""
    import mplfinance as mpf
    plot_df = df.rename(columns=str.capitalize)
    apds = []
    if "sma20" in df.columns:
        apds.append(mpf.make_addplot(df["sma20"], color="#2b8"))
    if "sma50" in df.columns:
        apds.append(mpf.make_addplot(df["sma50"], color="#e83"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    mpf.plot(
        plot_df, type="candle", volume=True, style="nightclouds",
        addplot=apds, title=f"{symbol}", savefig=dict(fname=str(out_path), dpi=120, bbox_inches="tight"),
    )
    return out_path


async def _ai_summary(agent, symbol: str, snap: dict, chart_path: str | None) -> str:
    system = (
        "You are a disciplined Indian markets analyst. Given an indicator snapshot, "
        "return exactly 5 bullet lines: trend, momentum, key levels (S/R numbers), "
        "one actionable trigger with condition + invalidation, one risk. No fluff."
    )
    user = (
        f"Symbol: {symbol}\n"
        f"Snapshot: {json.dumps(snap)}\n"
        f"Chart file (local): {chart_path or 'n/a'}"
    )
    try:
        return (await agent._ask(system, user)) or ""
    except Exception as e:
        return f"(llm error: {e})"


async def full_stack(
    symbol: str,
    period: str = "6mo",
    interval: str = "1d",
    chart: str = "plotly",     # "plotly" | "mplfinance" | "both" | "none"
    agent=None,
) -> dict:
    """One call — pulls data, computes indicators, renders chart(s), runs LLM."""
    df = fetch_ohlcv(symbol, period, interval)
    df = add_indicators(df)
    snap = _last_snapshot(df)

    ts = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
    safe_sym = symbol.replace("/", "_").replace("^", "")
    charts: dict[str, str] = {}
    if chart in ("plotly", "both"):
        try:
            p = render_plotly(df, symbol, CHART_DIR / f"{safe_sym}_{ts}.html")
            charts["plotly"] = str(p)
        except Exception as e:
            charts["plotly_error"] = str(e)
    if chart in ("mplfinance", "both"):
        try:
            p = render_mplfinance(df, symbol, CHART_DIR / f"{safe_sym}_{ts}.png")
            charts["mplfinance"] = str(p)
        except Exception as e:
            charts["mplfinance_error"] = str(e)

    bundle = {
        "symbol": symbol,
        "as_of": datetime.now(IST).isoformat(timespec="seconds"),
        "period": period,
        "interval": interval,
        "snapshot": snap,
        "charts": charts,
        "bars": len(df),
    }
    if agent is not None:
        bundle["ai_summary"] = await _ai_summary(
            agent, symbol, snap, charts.get("mplfinance") or charts.get("plotly"),
        )
    return bundle
