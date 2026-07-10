from __future__ import annotations
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date
from typing import Optional

import numpy as np

from config import INSTRUMENTS, LOT_SIZES, ATM_STEP, SENSEX_STEP, REQUEST_DELAY, TRADING
from groww.historical import (
    get_index_candles, get_expired_expiries,
    get_expired_option_key, get_expired_option_candles,
    is_trading_day, find_nearest_expiry, round_to_atm,
)
from data.candle_cache import get_candles as _cache_get, has_candles as _cache_has, save_candles as _cache_save
from backtest.simulator import simulate_trade
from indicators.calculator import calculate_all


def _get_spot_candles(instrument_key: str, date_str: str) -> list:
    """Cache-aware spot candle fetch. DB first, Upstox API on miss."""
    if _cache_has(instrument_key, date_str):
        return _cache_get(instrument_key, date_str)
    candles = get_index_candles(instrument_key, date_str)
    if candles:
        _cache_save(instrument_key, candles)
    time.sleep(REQUEST_DELAY)
    return candles


def _get_option_candles(opt_key: str, date_str: str, spot_candles: list | None = None) -> list:
    """Cache-aware synthetic option candle generator. Uses cached spot data when available."""
    if _cache_has(opt_key, date_str):
        return _cache_get(opt_key, date_str)
    candles = get_expired_option_candles(opt_key, date_str, spot_candles=spot_candles)
    if candles:
        _cache_save(opt_key, candles)
    return candles


def _time_str(candle) -> str:
    ts = str(candle[0])
    return ts[11:16] if len(ts) > 11 else ts[:5]


def _mins(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


@dataclass
class BacktestResult:
    instrument: str
    start_date: str
    end_date: str
    strategy: str = "First Candle Direction"
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    raw_pnl: float = 0.0
    sl_hits: int = 0
    tgt_hits: int = 0
    eod_exits: int = 0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    best_day: Optional[tuple] = None
    worst_day: Optional[tuple] = None
    win_rate_by_hour: dict = field(default_factory=dict)
    win_rate_by_day_of_week: dict = field(default_factory=dict)
    trades: list = field(default_factory=list)

    def print_report(self):
        from backtest.reporter import print_backtest_report
        print_backtest_report(self)

    def to_csv(self, filename: str):
        from backtest.reporter import export_to_csv
        export_to_csv(self, filename)


class BacktestEngine:
    def __init__(self, use_ai_brain: bool = False):
        self.use_ai_brain = use_ai_brain
        self._agent = None

    def _get_agent(self):
        if self._agent is None:
            from ai.agent import TradingAgent
            self._agent = TradingAgent()
        return self._agent

    def _get_step(self, instrument: str) -> int:
        return SENSEX_STEP if instrument == "SENSEX" else ATM_STEP

    def run(self, instrument: str, start_str: str, end_str: str, config: dict = None) -> BacktestResult:
        from backtest.strategies import get_signal, init_day, STRATEGIES
        config    = config or {}
        cfg_sl    = config.get("stop_loss_rs", TRADING["stop_loss_rs"])
        cfg_tgt   = config.get("target_rs",    TRADING["target_rs"])
        cfg_lots  = config.get("lots",         TRADING["lots"])
        strategy  = config.get("strategy",     "first_candle")
        strat_name = "AI Brain (Claude)" if self.use_ai_brain else STRATEGIES.get(strategy, strategy)

        # Max trades per day and daily loss limit
        max_trades_per_day = config.get("max_trades_per_day", 2)
        max_daily_loss     = config.get("max_daily_loss", TRADING.get("max_daily_loss", 3000))

        instrument_key = INSTRUMENTS.get(instrument)
        if not instrument_key:
            raise ValueError(f"Unknown instrument: {instrument}")

        lot_size = LOT_SIZES[instrument]
        step     = self._get_step(instrument)

        start = datetime.strptime(start_str, "%Y-%m-%d").date()
        end   = datetime.strptime(end_str,   "%Y-%m-%d").date()

        print(f"[backtest] {instrument} | {start_str} -> {end_str} | strategy={strat_name} | AI={self.use_ai_brain} | max_trades/day={max_trades_per_day}")

        expiries = get_expired_expiries(instrument_key)

        result = BacktestResult(instrument=instrument, start_date=start_str, end_date=end_str,
                                strategy=strat_name)
        daily_pnls: list = []
        day_of_week_trades: dict = {d: {"w": 0, "t": 0} for d in ["Mon","Tue","Wed","Thu","Fri"]}
        hour_trades: dict = {}
        prev_close = 0.0

        current = start
        while current <= end:
            if not is_trading_day(current):
                current += timedelta(days=1)
                continue

            date_str = current.strftime("%Y-%m-%d")
            spot_candles = _get_spot_candles(instrument_key, date_str)

            if not spot_candles or len(spot_candles) < 20:
                current += timedelta(days=1)
                continue

            spot_candles.sort(key=lambda c: c[0])
            expiry = find_nearest_expiry(expiries, date_str) or date_str
            dow    = current.strftime("%a")
            todays_close = float(spot_candles[-1][4])

            # ── Per-day state ────────────────────────────────────────────────
            day_trades   = 0
            day_pnl      = 0.0
            last_entry_time = ""

            if self.use_ai_brain:
                day_result = self._run_ai_day(
                    instrument, instrument_key, date_str, spot_candles,
                    expiry, step, lot_size, cfg_sl, cfg_tgt, cfg_lots,
                    prev_close, max_trades_per_day, max_daily_loss,
                )
            else:
                day_state = init_day(strategy, spot_candles, prev_close)

                day_result = self._run_strategy_day(
                    strategy, instrument, instrument_key, date_str,
                    spot_candles, expiry, step, lot_size,
                    cfg_sl, cfg_tgt, cfg_lots,
                    day_state, max_trades_per_day, max_daily_loss,
                )

            # Aggregate results
            for trade in day_result:
                is_win = trade["pnl_final"] > 0
                result.total_trades += 1
                result.total_pnl    += trade["pnl_final"]
                result.raw_pnl      += trade["pnl_raw"]
                day_pnl             += trade["pnl_final"]

                if is_win:
                    result.wins += 1
                else:
                    result.losses += 1

                if trade["exit_reason"] == "SL":
                    result.sl_hits += 1
                elif trade["exit_reason"] == "TARGET":
                    result.tgt_hits += 1
                else:
                    result.eod_exits += 1

                if dow in day_of_week_trades:
                    day_of_week_trades[dow]["t"] += 1
                    if is_win:
                        day_of_week_trades[dow]["w"] += 1

                # Hour-of-entry win rate
                entry_hour = trade.get("entry_time", "09:16")[:2]
                if entry_hour not in hour_trades:
                    hour_trades[entry_hour] = {"w": 0, "t": 0}
                hour_trades[entry_hour]["t"] += 1
                if is_win:
                    hour_trades[entry_hour]["w"] += 1

                result.trades.append(trade)
                print(
                    f"  {date_str} [{trade.get('entry_time','?')}] "
                    f"{trade['action']} {trade['strike']}{trade['option_type']} exp={trade['expiry']} | "
                    f"entry=Rs{trade['entry_price']:.1f} exit=Rs{trade['exit_price']:.1f} "
                    f"P&L=Rs{trade['pnl_final']:,.0f} [{trade['exit_reason']}]"
                )

            if day_pnl != 0:
                daily_pnls.append(day_pnl)

            prev_close = todays_close
            current += timedelta(days=1)

        self._compute_stats(result, daily_pnls, day_of_week_trades, hour_trades)
        return result

    def _run_strategy_day(
        self, strategy, instrument, instrument_key, date_str,
        spot_candles, expiry, step, lot_size,
        cfg_sl, cfg_tgt, cfg_lots,
        day_state, max_trades_per_day, max_daily_loss,
    ) -> list:
        """
        Scan every 5-min bar. On signal, enter ATM option, simulate forward,
        record result, then continue scanning from after the exit candle.
        """
        from backtest.strategies import get_signal, record_exit

        trades = []
        day_pnl = 0.0
        last_trade = None
        trades_today = 0

        # Build list of 5-min checkpoints: every 5th 1-min candle from 9:30
        check_times = []
        for c in spot_candles:
            t = _time_str(c)
            if "09:30" <= t <= "14:20":
                m = _mins(t)
                if (m - _mins("09:15")) % 5 == 0:
                    check_times.append(t)

        # Use a pointer into spot_candles to track current position
        # We skip candles that are part of an active trade
        skip_until_mins = 0

        for bar_time in check_times:
            if _mins(bar_time) < skip_until_mins:
                continue
            if trades_today >= max_trades_per_day:
                break
            if day_pnl <= -max_daily_loss:
                break

            # Candles up to and including this bar
            candles_so_far = [c for c in spot_candles if _time_str(c) <= bar_time]
            if not candles_so_far:
                continue

            signal = get_signal(strategy, candles_so_far, day_state, last_trade)
            if not signal:
                continue

            # Find entry price: open of next 1-min candle
            next_candles = [c for c in spot_candles if _time_str(c) > bar_time]
            if not next_candles:
                continue
            entry_candle = next_candles[0]
            entry_time   = _time_str(entry_candle)

            option_type = "CE" if signal == "BUY_CE" else "PE"
            spot_open   = float(entry_candle[1])
            atm_strike  = round_to_atm(spot_open, step)

            opt_key = get_expired_option_key(instrument_key, expiry, atm_strike, option_type)
            if not opt_key:
                print(f"  [{date_str}] no opt key for {atm_strike}{option_type} exp={expiry}")
                continue

            opt_candles = _get_option_candles(opt_key, date_str, spot_candles=spot_candles)
            if not opt_candles:
                print(f"  [{date_str}] no opt candles for {opt_key}")
                continue
            opt_candles.sort(key=lambda c: c[0])

            # Find matching option candle at entry time
            opt_entry_idx = next(
                (i for i, c in enumerate(opt_candles) if _time_str(c) >= entry_time),
                None
            )
            if opt_entry_idx is None:
                continue

            entry_price     = float(opt_candles[opt_entry_idx][1])
            candles_after   = opt_candles[opt_entry_idx + 1:]

            # Filter candles_after to only go up to 15:15
            candles_after = [c for c in candles_after if _time_str(c) <= "15:15"]
            if not candles_after:
                continue

            trade_result = simulate_trade(
                entry_price=entry_price,
                candles_after_entry=candles_after,
                sl_rs=cfg_sl,
                target_rs=cfg_tgt,
                lot_size=lot_size,
                lots=cfg_lots,
                trailing_sl_trigger=TRADING["trailing_sl_trigger"],
                trailing_sl_step=TRADING["trailing_sl_step"],
            )
            if not trade_result:
                continue

            # Find the exit time so we can skip past it
            exit_candle_idx = trade_result.exit_candle_idx
            if exit_candle_idx < len(candles_after):
                exit_time = _time_str(candles_after[exit_candle_idx])
                skip_until_mins = _mins(exit_time) + 1
            else:
                skip_until_mins = _mins("15:30")

            exit_time_str = _time_str(candles_after[exit_candle_idx]) if exit_candle_idx < len(candles_after) else "15:15"
            record_exit(day_state, option_type, exit_time_str, trade_result.exit_reason)

            day_pnl      += trade_result.pnl_final
            trades_today += 1

            trades.append({
                "date":        date_str,
                "instrument":  instrument,
                "action":      signal,
                "strike":      atm_strike,
                "option_type": option_type,
                "expiry":      expiry,
                "entry_time":  entry_time,
                "entry_price": round(trade_result.entry_price, 2),
                "exit_price":  round(trade_result.exit_price, 2),
                "exit_reason": trade_result.exit_reason,
                "quantity":    trade_result.quantity,
                "pnl_raw":     round(trade_result.pnl_raw, 2),
                "pnl_final":   round(trade_result.pnl_final, 2),
            })

            last_trade = trades[-1]

            if day_pnl <= -max_daily_loss:
                break

        return trades

    def _run_ai_day(
        self, instrument, instrument_key, date_str, spot_candles,
        expiry, step, lot_size, cfg_sl, cfg_tgt, cfg_lots,
        prev_close, max_trades_per_day, max_daily_loss,
    ) -> list:
        """AI brain multi-trade day: ask Claude every 5-min bar."""
        from indicators.calculator import calculate_price_structure, resample_5min

        trades = []
        day_pnl = 0.0
        trades_today = 0
        skip_until_mins = _mins("09:30")

        check_times = []
        for c in spot_candles:
            t = _time_str(c)
            if "09:30" <= t <= "14:20":
                m = _mins(t)
                if (m - _mins("09:15")) % 5 == 0:
                    check_times.append(t)

        for bar_time in check_times:
            if _mins(bar_time) < skip_until_mins:
                continue
            if trades_today >= max_trades_per_day:
                break
            if day_pnl <= -max_daily_loss:
                break

            candles_so_far = [c for c in spot_candles if _time_str(c) <= bar_time]
            if len(candles_so_far) < 20:
                continue

            spot_price = float(candles_so_far[-1][4])
            spot_change_pct = ((spot_price - prev_close) / prev_close * 100) if prev_close > 0 else 0.0
            candles_5m = resample_5min(candles_so_far)
            indicators = calculate_all(candles_so_far)
            price_structure = calculate_price_structure(candles_5m)

            context = {
                "instrument":       instrument,
                "date":             date_str,
                "spot_price":       spot_price,
                "spot_change_pct":  round(spot_change_pct, 2),
                "last_10_candles":  candles_5m[-12:],
                "indicators":       indicators,
                "price_structure":  price_structure,
                "options_snapshot": {"atm_strike": round_to_atm(spot_price, step)},
                "open_positions":   [],
                "today_pnl":        day_pnl,
                "premarket_bias":   {},
                "time_of_day":      bar_time,
                "capital_info":     {"initial": 100000, "current": 100000,
                                     "available": 100000, "locked": 0, "used_pct": 0},
            }
            try:
                decision = self._get_agent().decide_trade_sync(context)
            except Exception as e:
                print(f"  {date_str} {bar_time} | AI error: {e}")
                continue

            signal = decision.get("action", "NO_TRADE")
            print(f"  {date_str} {bar_time} | AI -> {signal} conf={decision.get('confidence',0)}")

            if signal not in ("BUY_CE", "BUY_PE"):
                continue

            option_type = "CE" if signal == "BUY_CE" else "PE"
            atm_strike  = round_to_atm(spot_price, step)

            next_candles = [c for c in spot_candles if _time_str(c) > bar_time]
            if not next_candles:
                continue
            entry_time = _time_str(next_candles[0])

            opt_key = get_expired_option_key(instrument_key, expiry, atm_strike, option_type)
            if not opt_key:
                continue

            opt_candles = _get_option_candles(opt_key, date_str, spot_candles=spot_candles)
            if not opt_candles:
                continue
            opt_candles.sort(key=lambda c: c[0])

            opt_entry_idx = next(
                (i for i, c in enumerate(opt_candles) if _time_str(c) >= entry_time),
                None
            )
            if opt_entry_idx is None:
                continue

            entry_price   = float(opt_candles[opt_entry_idx][1])
            candles_after = [c for c in opt_candles[opt_entry_idx + 1:] if _time_str(c) <= "15:15"]
            if not candles_after:
                continue

            trade_result = simulate_trade(
                entry_price=entry_price,
                candles_after_entry=candles_after,
                sl_rs=cfg_sl,
                target_rs=cfg_tgt,
                lot_size=lot_size,
                lots=cfg_lots,
                trailing_sl_trigger=TRADING["trailing_sl_trigger"],
                trailing_sl_step=TRADING["trailing_sl_step"],
            )
            if not trade_result:
                continue

            exit_candle_idx = trade_result.exit_candle_idx
            if exit_candle_idx < len(candles_after):
                skip_until_mins = _mins(_time_str(candles_after[exit_candle_idx])) + 1
            else:
                skip_until_mins = _mins("15:30")

            day_pnl      += trade_result.pnl_final
            trades_today += 1

            trades.append({
                "date":        date_str,
                "instrument":  instrument,
                "action":      signal,
                "strike":      atm_strike,
                "option_type": option_type,
                "expiry":      expiry,
                "entry_time":  entry_time,
                "entry_price": round(trade_result.entry_price, 2),
                "exit_price":  round(trade_result.exit_price, 2),
                "exit_reason": trade_result.exit_reason,
                "quantity":    trade_result.quantity,
                "pnl_raw":     round(trade_result.pnl_raw, 2),
                "pnl_final":   round(trade_result.pnl_final, 2),
            })

        return trades

    def _compute_stats(self, result: BacktestResult, daily_pnls: list, dow_trades: dict, hour_trades: dict):
        if result.total_trades == 0:
            return

        result.win_rate = result.wins / result.total_trades * 100

        gross_profit = sum(p for p in daily_pnls if p > 0)
        gross_loss   = abs(sum(p for p in daily_pnls if p < 0))
        result.profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        if len(daily_pnls) > 1:
            arr = np.array(daily_pnls)
            result.sharpe_ratio = round(float(arr.mean() / arr.std() * np.sqrt(252)), 2) if arr.std() > 0 else 0.0
        else:
            result.sharpe_ratio = 0.0

        peak = 0.0
        dd   = 0.0
        cumulative = 0.0
        for p in daily_pnls:
            cumulative += p
            if cumulative > peak:
                peak = cumulative
            dd = min(dd, cumulative - peak)
        result.max_drawdown     = round(abs(dd), 2)
        result.max_drawdown_pct = round(abs(dd) / max(peak, 1) * 100, 2)

        dated = [(t["date"], t["pnl_final"]) for t in result.trades]
        if dated:
            result.best_day  = max(dated, key=lambda x: x[1])
            result.worst_day = min(dated, key=lambda x: x[1])

        result.win_rate_by_day_of_week = {
            day: round(v["w"] / v["t"] * 100, 1) if v["t"] > 0 else 0.0
            for day, v in dow_trades.items()
        }
        result.win_rate_by_hour = {
            hr: round(v["w"] / v["t"] * 100, 1) if v["t"] > 0 else 0.0
            for hr, v in hour_trades.items()
        }
