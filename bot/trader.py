from __future__ import annotations
import asyncio
from datetime import datetime, timedelta

import pytz

# Shared yfinance + curl_cffi impersonation session (see data/yfsession.py).
# Yahoo blocks bare requests from datacenter IPs; the impersonation session is
# what makes the same yfinance calls succeed on the cloud host.
try:
    import yfinance as yf
    _YF_OK = True
except ImportError:
    yf = None
    _YF_OK = False

from data.yfsession import _SESSION as _YF_SESSION

from config import TRADING, INSTRUMENTS, LOT_SIZES
from bot.order_executor import OrderExecutor
from data.store import store
from data import database as db
from bot.risk import calc_quantity, check_risk_limits, max_positions_reached, lots_from_confidence
from bot.strategy import build_market_context
from bot.decision_log import DecisionLog
from bot.fees import apply_slippage, realistic_pnl
from groww.historical import (
    get_index_candles, get_live_option_from_chain, round_to_atm,
    get_india_vix, get_option_chain_analytics,
)
from groww.quotes import fetch_option_ltps
from groww.live_feed import request_option_subscribe

_executor = OrderExecutor()  # one instance for the session

IST = pytz.timezone("Asia/Kolkata")
_telegram_enabled = False


async def _send_telegram(msg: str):
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        from telegram import Bot
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)
    except Exception as e:
        print(f"[trader] Telegram error: {e}")


def _yf_last_and_change(symbol: str) -> tuple:
    """Returns (last_close, pct_change_vs_prev) or ('N/A', 0)."""
    try:
        t = yf.Ticker(symbol, session=_YF_SESSION) if _YF_SESSION else yf.Ticker(symbol)
        h = t.history(period="5d")
        if h.empty or len(h) < 1:
            return ("N/A", 0)
        last = float(h["Close"].iloc[-1])
        prev = float(h["Close"].iloc[-2]) if len(h) >= 2 else last
        pct  = round((last - prev) / prev * 100, 2) if prev else 0
        return (round(last, 2), pct)
    except Exception as e:
        print(f"[trader] yf error {symbol}: {e}")
        return ("N/A", 0)


async def _fetch_global_cues() -> dict:
    result = {
        "sgx_nifty": "N/A", "sgx_change": 0,
        "dow_futures": "N/A", "dow_change": 0,
        "nasdaq_futures": "N/A", "nasdaq_change": 0,
        "crude": "N/A", "crude_change": 0,
        "dxy": "N/A",
        "india_vix": "N/A",
        "prev_nifty": "N/A", "prev_banknifty": "N/A",
        "prev_pcr": "N/A",
    }
    if not _YF_OK:
        return result
    loop = asyncio.get_running_loop()
    try:
        # Run all yfinance calls concurrently in threads (they're blocking HTTP)
        symbols = {
            "sgx":    "^NSEI",     # SGX Nifty delisted; use NSEI as proxy
            "dow":    "YM=F",      # Dow Jones Mini futures
            "nasdaq": "NQ=F",      # Nasdaq 100 futures
            "crude":  "CL=F",      # Crude oil futures
            "dxy":    "DX-Y.NYB",  # Dollar index
            "vix":    "^INDIAVIX",
            "nifty":  "^NSEI",
            "bn":     "^NSEBANK",
        }
        tasks = {k: loop.run_in_executor(None, _yf_last_and_change, v) for k, v in symbols.items()}
        vals  = {k: await t for k, t in tasks.items()}

        result["sgx_nifty"],      result["sgx_change"]    = vals["sgx"]
        result["dow_futures"],    result["dow_change"]    = vals["dow"]
        result["nasdaq_futures"], result["nasdaq_change"] = vals["nasdaq"]
        result["crude"],          result["crude_change"]  = vals["crude"]
        result["dxy"], _ = vals["dxy"]
        result["india_vix"], _   = vals["vix"]
        # prev-day close for indices = value at index -2 in 5d history
        try:
            def _mk(s):
                return yf.Ticker(s, session=_YF_SESSION) if _YF_SESSION else yf.Ticker(s)
            nh = _mk("^NSEI").history(period="5d")
            bh = _mk("^NSEBANK").history(period="5d")
            result["prev_nifty"]     = round(float(nh["Close"].iloc[-2]), 2) if len(nh) >= 2 else "N/A"
            result["prev_banknifty"] = round(float(bh["Close"].iloc[-2]), 2) if len(bh) >= 2 else "N/A"
        except Exception:
            pass
    except Exception as e:
        print(f"[trader] global cues error: {e}")
    return result


class LiveTrader:
    def __init__(self, agent, learner=None):
        self.agent   = agent
        self.learner = learner
        self._market_open = False
        self._expiries_cache: dict = {}
        self._recent_entries: list[dict] = []   # tracks entries for correlated-position guard
        self._daily_loss_breaker_hit = False
        self._knowledge_cache: tuple[str, str] = ("", "")  # (date, formatted block)
        # Cache heavy per-tick fetches so the 5-min loop doesn't bombard Yahoo /
        # Groww when they slow down. VIX changes intraday but 3-5 min cache is
        # plenty; global cues are premarket-relevant so 30 min is fine.
        self._vix_cache: tuple[float, float] = (0.0, 0.0)          # (value, epoch)
        self._global_cues_cache: tuple[dict, float] = ({}, 0.0)    # (dict, epoch)
        self._profit_lock_engaged = False   # once tripped, open positions are pinned to BE

    async def _cached_vix(self, ttl: int = 240) -> float:
        """India VIX cached for `ttl` seconds. Yahoo/Upstox are the slow calls
        that were making the 5-min tick sluggish; VIX doesn't move enough in
        4 minutes to warrant re-fetching every tick."""
        import time as _t
        val, ts = self._vix_cache
        if val and (_t.time() - ts) < ttl:
            return val
        try:
            v = await asyncio.get_running_loop().run_in_executor(None, get_india_vix)
        except Exception:
            v = 0.0
        if v and v > 0:
            self._vix_cache = (float(v), _t.time())
            return float(v)
        return val or 0.0

    async def _cached_global_cues(self, ttl: int = 1800) -> dict:
        """Global cues (Dow/Nasdaq/Crude/DXY) barely move during Indian market
        hours. 30-min cache slashes yfinance load and keeps ticks snappy."""
        import time as _t
        cues, ts = self._global_cues_cache
        if cues and (_t.time() - ts) < ttl:
            return cues
        cues = await _fetch_global_cues()
        self._global_cues_cache = (cues, _t.time())
        return cues

    async def premarket_analysis(self):
        if store.bot_paused:
            print("[trader] premarket skipped - bot is paused")
            store.ai_status = "paused"
            return
        store.ai_status = "analyzing"
        global_data = await self._cached_global_cues(ttl=0)   # fresh at premarket
        # Fetch India VIX via Upstox (more reliable than yfinance)
        vix = await asyncio.get_running_loop().run_in_executor(None, get_india_vix)
        if vix and vix > 0:
            global_data["india_vix"] = vix
            store.india_vix = vix
        # Include today's news pulse in the premarket plan
        if store.news_insight:
            ni = store.news_insight
            global_data["news_block"] = (
                f"{ni.get('sentiment', 'NEUTRAL')} (score {ni.get('score', 0):+d}) — {ni.get('summary', '')}\n"
                f"Risk flags: {', '.join(ni.get('risk_flags', []) or ['none'])}"
            )
        plan = await self.agent.premarket_analysis(global_data)
        store.premarket_bias = plan
        store.ai_status = "waiting"
        print(f"[trader] Day plan: {plan.get('bias')} | Risk: {plan.get('risk_level')} | VIX={vix}")
        await _send_telegram(f"📊 MAP TRADE Day Plan: {plan.get('bias')} | Risk: {plan.get('risk_level')}\n{plan.get('reasoning','')}")
        self._market_open = True

    def _check_market_open(self) -> bool:
        from datetime import datetime
        from config import is_market_day
        now = datetime.now(IST)
        if not is_market_day(now.date()):
            return False
        mins = now.hour * 60 + now.minute
        return 9 * 60 + 15 <= mins <= 15 * 60 + 30

    async def _knowledge_block(self) -> str:
        """Top lessons from the knowledge base, formatted for the decision prompt.
        Cached per day — knowledge only changes via morning news scan / EOD report."""
        today = datetime.now(IST).strftime("%Y-%m-%d")
        if self._knowledge_cache[0] == today:
            return self._knowledge_cache[1]
        try:
            lessons = await db.get_knowledge(limit=12)
        except Exception:
            lessons = []
        block = "\n".join(
            f"- [{le.get('category', '?')}] {le.get('lesson', '')}" for le in lessons
        ) or "No accumulated lessons yet."
        self._knowledge_cache = (today, block)
        return block

    async def market_loop_tick(self):
        if store.bot_paused:
            store.ai_status = "paused"
            return
        if not self._market_open:
            # Auto-enable if we're within market hours (bot started late)
            if self._check_market_open():
                print("[trader] market_open flag was False but market is open — enabling now")
                self._market_open = True
            else:
                return

        now  = datetime.now(IST)
        time_str = now.strftime("%H:%M")
        next_tick = now.replace(second=0, microsecond=0) + timedelta(minutes=5)
        store.next_check_time = next_tick.strftime("%H:%M")

        # Manual override — operator paused the bot from dashboard
        if store.bot_paused:
            store.ai_status = "paused"
            return

        store.ai_status = "analyzing"
        store.last_tick_time = now.strftime("%H:%M:%S")
        store.tick_count += 1

        # Daily max-loss circuit breaker
        if not self._daily_loss_breaker_hit and store.total_pnl <= -abs(TRADING.get("max_daily_loss", 3000)):
            self._daily_loss_breaker_hit = True
            print(f"[trader] CIRCUIT BREAKER — daily loss ₹{store.total_pnl:,.0f} hit limit. No new trades today.")
            for pos in list(store.positions):
                await self._exit_position(pos, reason="CIRCUIT_BREAKER")
        if self._daily_loss_breaker_hit:
            store.ai_status = "waiting"
            return

        # Cached India VIX (4-min TTL) — was hammering the endpoint every tick
        vix = await self._cached_vix()
        if vix and vix > 0:
            store.india_vix = vix

        # Session profit-lock trigger: pin every open position's SL to entry.
        # Fires once per day; keeps entries open (do NOT stop hunting new setups)
        # but guarantees gains banked so far cannot flip to a loss.
        profit_lock = TRADING.get("session_profit_lock", 0)
        if profit_lock and store.realized_pnl >= profit_lock and not self._profit_lock_engaged:
            self._profit_lock_engaged = True
            for pos in store.positions:
                if pos.get("sl", 0) < pos.get("entry", 0):
                    print(f"[trader] profit-lock @ ₹{store.realized_pnl:.0f} — pinning "
                          f"{pos['instrument']} {pos['strike']}{pos['type']} SL to entry "
                          f"{pos['entry']:.2f} (was {pos['sl']:.2f})")
                    pos["sl"] = round(float(pos["entry"]), 2)

        try:
            # Refresh option LTPs for all open positions
            if store.positions:
                ltps = await asyncio.get_running_loop().run_in_executor(
                    None, fetch_option_ltps, store.positions
                )
                for pos in list(store.positions):
                    key = f"{pos['instrument']}_{pos['strike']}_{pos['type']}"
                    if key in ltps:
                        pos["ltp"] = ltps[key]
                        pos["pnl"] = round((ltps[key] - pos["entry"]) * pos["quantity"], 2)
                        store.option_prices[key] = ltps[key]
                        if ltps[key] <= pos["sl"]:
                            await self._exit_position(pos, reason="SL", current_price=ltps[key])
                        elif ltps[key] >= pos["target"]:
                            await self._exit_position(pos, reason="TARGET", current_price=ltps[key])
                        else:
                            await self._maybe_partial_book(pos, ltps[key])

            for instrument in ["NIFTY", "BANKNIFTY", "SENSEX"]:
                await self._process_instrument(instrument, time_str)

            # AI-driven manage — ask Claude what to do with EVERY open position
            # (both profitable AND losing). Previously we only polled the AI on
            # profitable positions; losing trades were left to grind to full SL
            # even when the setup had already been invalidated. CUT_EARLY lets
            # the AI abandon a broken thesis at a small loss instead of taking
            # the full stop.
            for position in list(store.positions):
                current_price = store.option_prices.get(
                    f"{position['instrument']}_{position['strike']}_{position['type']}", position["ltp"]
                )
                try:
                    trail = await self.agent.check_trailing_sl(position, current_price)
                except Exception as e:
                    print(f"[trader] trailing SL AI error: {e}")
                    continue
                t_action = trail.get("action", "HOLD")
                if t_action == "MOVE_SL":
                    new_sl = trail.get("new_sl")
                    if (isinstance(new_sl, (int, float))
                            and new_sl > position["sl"]
                            and new_sl < current_price):
                        print(f"[trader] AI trailing SL {position['instrument']} {position['strike']}{position['type']}: "
                              f"{position['sl']:.2f} → {new_sl:.2f} (ltp={current_price:.2f}) | {trail.get('reason','')}")
                        position["sl"] = round(float(new_sl), 2)
                elif t_action == "EXIT":
                    print(f"[trader] AI exit (profitable) {position['instrument']} {position['strike']}{position['type']} | {trail.get('reason','')}")
                    await self._exit_position(position, reason="AI_EXIT", current_price=current_price)
                elif t_action == "CUT_EARLY":
                    # Only honour CUT_EARLY when the position is genuinely under
                    # water or flat — never let the AI abandon a winner via this
                    # path; that's what EXIT is for.
                    if current_price <= position["entry"]:
                        print(f"[trader] AI cut-early {position['instrument']} {position['strike']}{position['type']} "
                              f"@ {current_price:.2f} (entry {position['entry']:.2f}) | {trail.get('reason','')}")
                        await self._exit_position(position, reason="AI_CUT_EARLY", current_price=current_price)
                    else:
                        print("[trader] ignoring CUT_EARLY on profitable trade — treat as HOLD")

        except Exception as e:
            import traceback
            err_msg = f"[trader] tick error at {time_str}: {e}\n{traceback.format_exc()}"
            print(err_msg)
            try:
                await _send_telegram(f"❌ Core Market Loop Tick Crashed!\nError: {e}")
            except Exception:
                pass

        finally:
            store.ai_status = "in_trade" if store.positions else "waiting"

    async def emergency_square_off(self) -> int:
        """Exit every open position immediately and pause the bot.

        Each exit is isolated: if one position fails to close (broker/network
        error), we still attempt the rest — an emergency circuit-breaker must
        never leave live positions open because one order threw."""
        store.bot_paused = True
        closed = 0
        failed = []
        for pos in list(store.positions):
            try:
                await self._exit_position(pos, reason="EMERGENCY_SQUARE_OFF")
                closed += 1
            except Exception as e:
                label = f"{pos.get('instrument')} {pos.get('strike')}{pos.get('type')}"
                failed.append(label)
                print(f"[trader] EMERGENCY square-off FAILED for {label}: {e}")

        msg = f"[MAP TRADE] Emergency square-off triggered. Closed {closed} position(s). Bot paused."
        if failed:
            msg += (f"\n⚠️ FAILED to close {len(failed)}: {', '.join(failed)} — "
                    "CHECK YOUR BROKER TERMINAL MANUALLY.")
        await _send_telegram(msg)
        store.ai_status = "waiting"
        return closed

    async def recover_active_positions(self):
        """Recover any open positions from database on startup."""
        try:
            open_trades = await db.get_open_trades()
            if not open_trades:
                print("[trader] No open positions to recover")
                return

            print(f"[trader] Recovering {len(open_trades)} active positions...")
            for trade in open_trades:
                sig_id = trade.get("signal_id")
                sl_premium = None
                target_premium = None
                if sig_id:
                    signal = await db.get_signal(sig_id)
                    if signal:
                        ai_resp_str = signal.get("ai_response")
                        if ai_resp_str:
                            try:
                                import json
                                ai_res = json.loads(ai_resp_str)
                                sl_premium = ai_res.get("sl_premium") or ai_res.get("sl")
                                target_premium = ai_res.get("target_premium") or ai_res.get("target")
                            except Exception:
                                pass
                        if sl_premium is None or target_premium is None:
                            dec_log_str = signal.get("decision_log")
                            if dec_log_str:
                                try:
                                    import json
                                    dec_log = json.loads(dec_log_str)
                                    if sl_premium is None:
                                        sl_premium = dec_log.get("sl") or dec_log.get("sl_premium")
                                    if target_premium is None:
                                        target_premium = dec_log.get("target") or dec_log.get("target_premium")
                                except Exception:
                                    pass

                instrument = trade.get("instrument")
                action = trade.get("action")
                option_type = "CE" if "CE" in action else "PE"
                step = 100 if instrument == "SENSEX" else 50
                
                spot_price = 0.0
                price_info = store.prices.get(instrument)
                if price_info:
                    spot_price = price_info.ltp

                if spot_price == 0.0:
                    try:
                        candles_data = await asyncio.get_running_loop().run_in_executor(
                            None, get_index_candles, instrument, "1m", 1
                        )
                        if candles_data and "candles" in candles_data and candles_data["candles"]:
                            spot_price = candles_data["candles"][-1]["close"]
                    except Exception as e:
                        print(f"[trader] Error fetching spot price for recovery: {e}")

                instrument_key = None
                ltp = trade.get("entry_price")
                try:
                    instrument_key_name = f"NSE-{instrument}-"
                    opt_data = await asyncio.get_running_loop().run_in_executor(
                        None, get_live_option_from_chain, instrument_key_name, spot_price, option_type, step
                    )
                    if opt_data:
                        instrument_key = opt_data.get("instrument_key")
                        ltp = opt_data.get("ltp", ltp)
                except Exception as e:
                    print(f"[trader] Error getting option chain for recovery: {e}")

                if not instrument_key:
                    expiry = trade.get("expiry")
                    strike = trade.get("strike")
                    instrument_key = f"NSE-{instrument}-{expiry}-{strike}-{option_type}"

                try:
                    request_option_subscribe(instrument_key)
                except Exception as e:
                    print(f"[trader] Error subscribing to recovered option feed: {e}")

                # Position dict MUST use the same keys as live entries ("entry",
                # not "entry_price") — the SL monitor, exit path, and capital
                # accounting all read pos["entry"]/["sl"]/["target"], and a
                # recovered position with missing keys would crash those loops
                # and run unprotected. When the signal carried no SL/target,
                # fall back to the configured percentages so the position is
                # never monitored against None.
                entry_price = float(trade["entry_price"])
                if not isinstance(sl_premium, (int, float)) or not sl_premium:
                    sl_premium = round(entry_price * (1 - TRADING.get("fallback_sl_pct", 0.30)), 2)
                if not isinstance(target_premium, (int, float)) or not target_premium:
                    target_premium = round(entry_price * (1 + TRADING.get("fallback_target_pct", 0.60)), 2)

                pos = {
                    "trade_db_id": trade["id"],
                    "instrument": trade["instrument"],
                    "action": trade["action"],
                    "strike": trade["strike"],
                    "expiry": trade["expiry"],
                    "entry": entry_price,
                    "entry_time": trade.get("entry_time"),
                    "quantity": trade["quantity"],
                    "signal_id": trade["signal_id"],
                    "instrument_key": instrument_key,
                    "ltp": ltp,
                    "pnl": round(((ltp or entry_price) - entry_price) * trade["quantity"], 2),
                    "sl": round(float(sl_premium), 2),
                    "target": round(float(target_premium), 2),
                    "type": option_type,
                }
                store.positions.append(pos)
                print(f"[trader] Recovered position: {pos}")
        except Exception as e:
            print(f"[trader] Error in recover_active_positions: {e}")

    def _log_skip(self, instrument: str, reason: str, time_str: str, log: DecisionLog | None = None):
        signal = {
            "time":       time_str,
            "instrument": instrument,
            "action":     "SKIP",
            "confidence": 0,
            "reason":     reason,
        }
        if log is not None:
            signal["decision_log"] = log.to_dict()
        store.add_signal(signal)
        print(f"[trader] SKIP {instrument} @ {time_str} - {reason}")
        if log is not None:
            for line in log.summary_lines():
                print(line)

    async def _process_instrument(self, instrument: str, time_str: str):
        instrument_key = INSTRUMENTS[instrument]
        date_str = datetime.now(IST).strftime("%Y-%m-%d")

        log = DecisionLog(instrument=instrument, time=time_str)

        candles = get_index_candles(instrument_key, date_str)
        if not candles:
            log.guard_block("CandleData", "No candle data from Upstox")
            log.finalize("SKIP", "no_candles")
            self._log_skip(instrument, "No candle data from Upstox", time_str, log)
            return
        log.guard_pass("CandleData", f"{len(candles)} candles loaded")
        candles.sort(key=lambda c: c[0])
        store.today_candles[instrument] = candles

        spot_price = float(candles[-1][4])
        # Don't overwrite real-time WS price with stale candle close
        if store.feed_status != "live":
            store.update_price(instrument, spot_price)

        # Use yesterday's close from store (set at startup) for correct daily change context
        prev_close = store.prices[instrument].prev_close or spot_price

        step       = 100 if instrument == "SENSEX" else 50
        atm_strike = round_to_atm(spot_price, step)
        current_vix = getattr(store, "india_vix", 0)

        # Detect expiry day (Nifty=Thu, BankNifty=Wed, Sensex=Fri) — info only, AI decides
        now_dt = datetime.now(IST)
        weekday = now_dt.weekday()
        _expiry_weekdays = {"NIFTY": 3, "BANKNIFTY": 2, "SENSEX": 4}
        is_expiry_day = weekday == _expiry_weekdays.get(instrument, 3)

        # Fetch option chain analytics (PCR, IV, OI, max pain) for current nearest expiry
        _today_str = date_str
        _expiry_cache_key = f"{instrument}_{_today_str}"
        nearest_expiry = self._expiries_cache.get(_expiry_cache_key)
        if not nearest_expiry:
            # Try next 8 days to find a valid Groww option chain expiry
            from datetime import date as _date
            from groww.auth import get_groww_client as _gc
            from groww.historical import _INSTRUMENT_MAP
            _client = _gc()
            _td = _date.today()
            _exch, _, _sym = _INSTRUMENT_MAP.get(instrument_key,
                ("NSE", "FNO", instrument_key.split("|")[-1]))
            _clean_sym = _sym.replace(" ", "")
            for _days in range(0, 8):
                _cand = (_td + timedelta(days=_days)).strftime("%Y-%m-%d")
                try:
                    _chain = _client.get_option_chain(
                        exchange=_exch, underlying_symbol=_clean_sym, expiry_date=_cand
                    )
                    _contracts = _chain if isinstance(_chain, list) else _chain.get("data", [])
                    if _contracts:
                        nearest_expiry = _cand
                        self._expiries_cache[_expiry_cache_key] = nearest_expiry
                        break
                except Exception:
                    pass

        chain_analytics = {}
        if nearest_expiry:
            chain_analytics = await asyncio.get_running_loop().run_in_executor(
                None, get_option_chain_analytics, instrument_key, spot_price, nearest_expiry, step
            )

        options_snapshot = {
            "atm_strike":  atm_strike,
            "pcr":         chain_analytics.get("pcr", "N/A"),
            "max_pain":    chain_analytics.get("max_pain", "N/A"),
            "atm_iv":      chain_analytics.get("atm_iv", "N/A"),
            "atm_ce_oi":   chain_analytics.get("atm_ce_oi", "N/A"),
            "atm_pe_oi":   chain_analytics.get("atm_pe_oi", "N/A"),
            "oi_change":   chain_analytics.get("oi_change", "N/A"),
            "days_to_exp": chain_analytics.get("days_to_exp", "N/A"),
            "india_vix":   current_vix or "N/A",
            "is_expiry_day": is_expiry_day,
        }

        context = build_market_context(
            instrument=instrument,
            spot_candles=candles,
            spot_price=spot_price,
            prev_close=prev_close,
            options_snapshot=options_snapshot,
            open_positions=store.positions,
            today_pnl=store.total_pnl,
            premarket_bias=store.premarket_bias,
            time_of_day=time_str,
            capital_info={
                "initial":   store.initial_capital,
                "available": round(store.capital_available, 2),
                "locked":    round(store.capital_locked, 2),
                "used_pct":  store.capital_used_pct,
                "current":   round(store.current_capital, 2),
            },
        )

        # Feed today's news pulse + accumulated knowledge into the AI prompt
        if store.news_insight:
            ni = store.news_insight
            risk = f" | RISK FLAGS: {'; '.join(ni.get('risk_flags', []))}" if ni.get("risk_flags") else ""
            context["news_pulse"] = (
                f"[updated {ni.get('updated', '?')}] {ni.get('sentiment', 'NEUTRAL')} "
                f"(score {ni.get('score', 0):+d}) — {ni.get('summary', '')}{risk}"
            )
        context["knowledge_lessons"] = await self._knowledge_block()

        store.update_indicators(instrument, context["indicators"])

        log.info("ContextBuilt",
                 f"phase={context.get('price_structure',{}).get('phase','?')} "
                 f"trend={context.get('price_structure',{}).get('trend_strength','?')} "
                 f"vix={current_vix} iv={options_snapshot.get('atm_iv')}",
                 spot=spot_price, atm=atm_strike,
                 pcr=options_snapshot.get("pcr"),
                 max_pain=options_snapshot.get("max_pain"))

        decision = await self.agent.decide_trade(context)
        decision["indicators"] = context["indicators"]
        log.set_ai(decision)

        # Persist signal with full decision_log + a compact market_context snapshot
        compact_ctx = {
            "indicators": context.get("indicators", {}),
            "price_structure": context.get("price_structure", {}),
            "options_snapshot": options_snapshot,
            "spot": spot_price,
            "vix": current_vix,
        }
        signal_id = await db.insert_signal(decision, decision_log=log.to_dict(), market_context=compact_ctx)
        store.add_signal({
            "time": time_str,
            "instrument": instrument,
            "action": decision.get("action"),
            "confidence": decision.get("confidence"),
            "reason": decision.get("reasoning", "")[:100],
            "decision_log": log.to_dict(),
        })

        action = decision.get("action")
        if action in ("BUY_CE", "BUY_PE") and not store.new_entries_enabled:
            log.guard_block("NewEntriesDisabled", "new entries blocked by operator override")
            log.finalize("SKIP", "new_entries_disabled")
            self._log_skip(instrument, "New entries disabled by operator", time_str, log)
            return

        if action in ("BUY_CE", "BUY_PE"):
            option_type = "CE" if action == "BUY_CE" else "PE"
            step = 100 if instrument == "SENSEX" else 50

            # ── Position-level guards ────────────────────────────────────────
            if max_positions_reached(store.positions):
                msg = f"Max positions reached ({len(store.positions)}/{TRADING['max_positions']})"
                log.guard_block("MaxPositions", msg)
                log.finalize("SKIP", "max_positions")
                self._log_skip(instrument, msg, time_str, log)
                return
            log.guard_pass("MaxPositions", f"{len(store.positions)}/{TRADING['max_positions']} open")

            if any(p["instrument"] == instrument and p["type"] == option_type
                   for p in store.positions):
                msg = f"Already holding an open {instrument} {option_type} position"
                log.guard_block("DuplicatePosition", msg)
                log.finalize("SKIP", "duplicate_position")
                self._log_skip(instrument, msg, time_str, log)
                return
            log.guard_pass("DuplicatePosition", "no open position in same instrument+direction")

            # Correlated-entry guard: NIFTY/BANKNIFTY/SENSEX move together, so a
            # same-direction entry across instruments within 5 minutes is the
            # same bet twice, not diversification.
            _cutoff = datetime.now(IST) - timedelta(minutes=5)
            if any(e["direction"] == option_type and e["time"] >= _cutoff
                   for e in self._recent_entries):
                msg = f"Correlated {option_type} entry in another index within last 5 min"
                log.guard_block("CorrelatedEntry", msg)
                log.finalize("SKIP", "correlated_entry")
                self._log_skip(instrument, msg, time_str, log)
                return
            log.guard_pass("CorrelatedEntry", "no correlated entries in last 5 min")

            # AI-selected strike offset (-2..+2) and expiry preference ("current" | "next").
            # Both are optional in the schema (defaults 0 / "current"), so pre-schema
            # decisions and older Ollama replies still work unchanged.
            ai_strike_offset = int(decision.get("strike_offset", 0) or 0)
            ai_strike_offset = max(-2, min(2, ai_strike_offset))
            ai_expiry_pref = str(decision.get("expiry_pref", "current") or "current").lower()
            if ai_expiry_pref not in ("current", "next"):
                ai_expiry_pref = "current"

            opt_data = await asyncio.get_running_loop().run_in_executor(
                None, get_live_option_from_chain,
                instrument_key, spot_price, option_type, step,
                ai_strike_offset, ai_expiry_pref,
            )
            log.info("StrikePick",
                     f"offset={ai_strike_offset:+d} expiry_pref={ai_expiry_pref}")
            if not opt_data:
                log.guard_block("OptionChain", "no ATM option found in chain")
                log.finalize("SKIP", "no_option_data")
                self._log_skip(instrument, "No option chain data", time_str, log)
                return

            entry_price = opt_data["ltp"]
            atm_strike  = opt_data["strike"]
            expiry      = opt_data["expiry"]
            opt_key     = opt_data["instrument_key"]

            if not entry_price:
                log.guard_block("OptionLTP", "entry price is 0 / unavailable")
                log.finalize("SKIP", "zero_ltp")
                return
            log.guard_pass("OptionChain", f"strike={atm_strike} ltp={entry_price} expiry={expiry}")

            # Realistic entry: pay the ask (apply slippage)
            entry_quote = entry_price
            vix_val = current_vix if isinstance(current_vix, (int, float)) and current_vix > 0 else 15.0
            entry_price = apply_slippage(entry_price, "buy", vix=vix_val)
            log.info("Slippage", f"quoted={entry_quote} -> fill@ask={entry_price}",
                     quoted=entry_quote, fill=entry_price)

            # Scale position size by AI confidence — conf 7-8 -> 2 lots, 9-10 -> 3 lots.
            # `check_risk_limits` still enforces max_risk_per_trade and may shrink
            # the resulting quantity if it exceeds ₹ risk cap.
            ai_conf = int(decision.get("confidence", 0) or 0)
            scaled_lots = lots_from_confidence(ai_conf)
            quantity = calc_quantity(instrument, lots=scaled_lots)
            if scaled_lots > TRADING.get("lots", 1):
                log.info("SizeScaling", f"conf={ai_conf} -> {scaled_lots} lots (base {TRADING.get('lots',1)})")

            # AI-provided SL/target from decision; fallback to % of entry if omitted
            ai_sl  = decision.get("sl_premium")
            ai_tgt = decision.get("target_premium")
            if isinstance(ai_sl, (int, float)) and ai_sl > 0 and ai_sl < entry_price:
                sl = round(float(ai_sl), 2)
            else:
                sl = round(entry_price * (1 - TRADING.get("fallback_sl_pct", 0.30)), 2)
            if isinstance(ai_tgt, (int, float)) and ai_tgt > entry_price:
                target = round(float(ai_tgt), 2)
            else:
                target = round(entry_price * (1 + TRADING.get("fallback_target_pct", 0.60)), 2)
            log.info("AI_SL_TP", f"sl={sl} tgt={target} (ai_sl={ai_sl} ai_tgt={ai_tgt})")

            # ── Hard gates + EV filter (plug the naked-buy -EV leak) ─────────
            # Cheap, explicit gates BEFORE committing capital. Defaults are
            # loose (conf>=4, VIX<=30) so normal setups pass; they only block
            # genuinely dangerous extremes and negative-expectancy geometry.
            from bot.spreads import passes_hard_gates, naked_buy_ev, confidence_to_pwin
            atm_oi_val = 0.0
            try:
                _ce = options_snapshot.get("atm_ce_oi")
                _pe = options_snapshot.get("atm_pe_oi")
                atm_oi_val = float(_ce or 0) + float(_pe or 0)
            except Exception:
                atm_oi_val = 0.0
            gates_ok, gate_reason = passes_hard_gates(
                ai_conf, vix_val, atm_oi_val,
                min_confidence=TRADING.get("hard_gate_min_conf", 4),
                vix_ceiling=TRADING.get("hard_gate_vix_ceiling", 30.0),
                min_liquidity_oi=TRADING.get("hard_gate_min_oi", 0),
            )
            if not gates_ok:
                log.guard_block("HardGate", gate_reason)
                log.finalize("SKIP", "hard_gate")
                self._log_skip(instrument, f"Hard gate: {gate_reason}", time_str, log)
                return
            log.guard_pass("HardGate", gate_reason)

            if TRADING.get("ev_gate_enabled", True):
                # Approximate round-trip fee per unit so EV is net of costs.
                _fee_per_unit = 40.0 / max(1, quantity)
                ev = naked_buy_ev(entry_price, sl, target,
                                  confidence_to_pwin(ai_conf), fees_per_unit=_fee_per_unit)
                if not ev.accept:
                    log.guard_block("EVGate", ev.reason)
                    log.finalize("SKIP", "ev_gate")
                    self._log_skip(instrument, f"EV gate: {ev.reason}", time_str, log)
                    return
                log.guard_pass("EVGate", ev.reason)

            # Session-level risk limits: profit lock, per-symbol trade cap,
            # consecutive-loss cooldown, and per-trade risk cap (may downsize
            # quantity to respect it).
            allowed, risk_reason, adj_qty = await check_risk_limits(
                instrument, action, entry_price, sl, quantity
            )
            if not allowed:
                log.guard_block("RiskLimits", risk_reason)
                log.finalize("SKIP", "risk_limits")
                self._log_skip(instrument, risk_reason, time_str, log)
                return
            if adj_qty != quantity:
                log.info("RiskLimits", risk_reason, old_qty=quantity, new_qty=adj_qty)
                quantity = adj_qty
            log.guard_pass("RiskLimits", risk_reason)

            trade_cost = round(entry_price * quantity, 2)
            if trade_cost > store.capital_available:
                msg = f"Insufficient capital - need ₹{trade_cost:,.0f}, have ₹{store.capital_available:,.0f}"
                log.guard_block("Capital", msg)
                log.finalize("SKIP", "insufficient_capital")
                self._log_skip(instrument, msg, time_str, log)
                return
            log.guard_pass("Capital", f"cost=₹{trade_cost:,.0f} within budget")

            entry_time = datetime.now(IST).isoformat()

            if TRADING["paper_trade"]:
                position = {
                    "instrument":     instrument,
                    "strike":         atm_strike,
                    "type":           option_type,
                    "action":         action,
                    "expiry":         expiry,
                    "entry":          entry_price,
                    "ltp":            entry_price,
                    "pnl":            0.0,
                    "sl":             sl,
                    "target":         target,
                    "quantity":       quantity,
                    "entry_time":     entry_time,
                    "signal_id":      signal_id,
                    "instrument_key": opt_key,
                }
                trade_db_id = await db.insert_trade({
                    "trade_type":    "paper",
                    "instrument":    instrument,
                    "action":        action,
                    "strike":        atm_strike,
                    "expiry":        expiry,
                    "entry_time":    entry_time,
                    "entry_price":   entry_price,
                    "quantity":      quantity,
                    "pnl_raw":       None,
                    "pnl_final":     None,
                    "signal_id":     signal_id,
                    "confidence":    decision.get("confidence"),
                    "entry_reason":  decision.get("reasoning", ""),
                    "capital_used":  trade_cost,
                    "capital_before": round(store.capital_available, 2),
                })
                position["trade_db_id"] = trade_db_id
                position["entry_log"] = log.to_dict()
                store.add_position(position)
                request_option_subscribe(opt_key)
                self._recent_entries.append({"instrument": instrument, "direction": option_type, "time": datetime.now(IST)})
                log.finalize("ENTERED", f"{action} {atm_strike}{option_type} @ {entry_price:.2f}",
                             trade_db_id=trade_db_id, sl=sl, target=target)
                print(f"[trader] PAPER {action} {atm_strike}{option_type} @ {entry_price:.2f} | SL={sl:.2f} TGT={target:.2f} | db_id={trade_db_id}")
                for line in log.summary_lines():
                    print(line)
                await _send_telegram(f"{instrument} {action} {atm_strike}{option_type} @ Rs {entry_price:.0f}\nConf={decision.get('confidence')}/10\nWhy: {decision.get('entry_trigger','')}")
            else:
                # LIVE TRADING — AngelOne SmartAPI
                # expiry must be in "09JAN25" format for AngelOne scrip master
                angel_expiry = datetime.strptime(expiry, "%Y-%m-%d").strftime("%d%b%y").upper()
                position = await _executor.enter(
                    instrument=instrument,
                    strike=atm_strike,
                    option_type=option_type,
                    expiry_str=angel_expiry,
                    quantity=quantity,
                    entry_price=entry_price,
                    sl=sl,
                    target=target,
                    store=store,
                    telegram_fn=_send_telegram,
                )
                if position is not None:
                    position["signal_id"]      = signal_id
                    position["instrument_key"] = opt_key
                    position["entry_log"]      = log.to_dict()
                    trade_db_id = await db.insert_trade({
                        "trade_type":     "live",
                        "instrument":     instrument,
                        "action":         action,
                        "strike":         atm_strike,
                        "expiry":         expiry,
                        "entry_time":     position["entry_time"],
                        "entry_price":    position["entry"],
                        "quantity":       quantity,
                        "pnl_raw":        None,
                        "pnl_final":      None,
                        "signal_id":      signal_id,
                        "confidence":     decision.get("confidence"),
                        "entry_reason":   decision.get("reasoning", ""),
                        "capital_used":   position["entry"] * quantity,
                        "capital_before": round(store.capital_available, 2),
                    })
                    position["trade_db_id"] = trade_db_id
                    store.add_position(position)
                    request_option_subscribe(opt_key)
                    self._recent_entries.append({"instrument": instrument, "direction": option_type, "time": datetime.now(IST)})
                    log.finalize("ENTERED_LIVE", f"{action} {atm_strike}{option_type} @ {position['entry']:.2f}",
                                 trade_db_id=trade_db_id, sl=sl, target=target, order_id=position.get("order_id"))
                    print(f"[trader] LIVE {action} {atm_strike}{option_type} @ {position['entry']:.2f} | SL={sl:.2f} TGT={target:.2f}")
        elif action not in ("EXIT_ALL",):
            # AI returned NO_TRADE / HOLD - record the decision trail anyway so we can review later
            log.finalize("NO_TRADE", decision.get("reasoning", "")[:120])
            for line in log.summary_lines():
                print(line)

        if action == "EXIT_ALL":
            for pos in list(store.positions):
                if pos["instrument"] == instrument:
                    await self._exit_position(pos, reason="ai_exit")

    async def _maybe_partial_book(self, position: dict, ltp: float):
        """Book half the position and move SL to breakeven once price has
        traversed `partial_book_ratio` of the entry-to-target distance. Fires
        at most once per position, and only when the size is at least 2 lots
        (a 1-lot position can't be split without dropping to zero)."""
        if not TRADING.get("partial_book_enabled", False):
            return
        if position.get("partial_booked"):
            return
        entry  = position.get("entry", 0)
        target = position.get("target", 0)
        qty    = position.get("quantity", 0)
        instr  = position.get("instrument")
        lot    = LOT_SIZES.get(instr, 0) if instr else 0
        # need >= 2 lots so half is still a valid tradable qty
        if not (entry > 0 and target > entry and lot > 0 and qty >= 2 * lot):
            return

        ratio = float(TRADING.get("partial_book_ratio", 0.60))
        trigger = entry + (target - entry) * ratio
        if ltp < trigger:
            return

        # Split into "half we book now" and "rest we let ride". Half must be a
        # whole-lot multiple; round down so we never over-book.
        half_lots = max(1, (qty // lot) // 2)
        book_qty  = half_lots * lot
        keep_qty  = qty - book_qty
        if book_qty <= 0 or keep_qty <= 0:
            return

        # Book the "half" as an independent exit — full fee stack, real slippage.
        vix_val = getattr(store, "india_vix", 15.0)
        vix_val = vix_val if isinstance(vix_val, (int, float)) and vix_val > 0 else 15.0
        exit_quote = ltp
        exit_fill  = apply_slippage(ltp, "sell", vix=vix_val) if not position.get("is_live") else ltp
        breakdown  = realistic_pnl(entry, exit_fill, book_qty)
        pnl_raw    = breakdown["pnl_raw"]
        pnl_final  = breakdown["pnl_final"]
        fees_total = breakdown["fees"]["total"]
        slippage_cost = round((exit_quote - exit_fill) * book_qty, 2)

        store.realized_pnl   += pnl_final
        store.cumulative_pnl += pnl_final

        # Shrink the live position to the remainder, tighten SL to breakeven so
        # the "runner" is now a free trade. Flag is set BEFORE any await so the
        # concurrent sl_monitor / tick loops can never double-book the same
        # position (cooperative scheduling only yields at awaits).
        position["quantity"]       = keep_qty
        position["partial_booked"] = True
        if position.get("sl", 0) < entry:
            position["sl"] = round(float(entry), 2)

        # Keep DB rows internally consistent: the parent trade row becomes the
        # runner (quantity reduced to keep_qty, still open); a separate CLOSED
        # row records the booked half. Neither row double-counts quantity.
        exit_time = datetime.now(IST).isoformat()
        try:
            parent_id = position.get("trade_db_id")
            if parent_id:
                await db.update_trade_quantity(parent_id, keep_qty)
            await db.insert_trade({
                "trade_type":   "paper" if not position.get("is_live") else "live",
                "instrument":   position["instrument"],
                "action":       position.get("action", f"BUY_{position['type']}"),
                "strike":       position["strike"],
                "expiry":       position["expiry"],
                "entry_time":   position["entry_time"],
                "entry_price":  entry,
                "exit_time":    exit_time,
                "exit_price":   exit_fill,
                "exit_reason":  "PARTIAL_BOOK",
                "quantity":     book_qty,
                "pnl_raw":      pnl_raw,
                "pnl_final":    pnl_final,
                "fees_total":   fees_total,
                "slippage_cost": slippage_cost,
                "signal_id":    position.get("signal_id"),
            })
        except Exception as e:
            print(f"[trader] partial-book DB write failed: {e}")

        print(f"[trader] PARTIAL BOOK {position['instrument']} {position['strike']}{position['type']} "
              f"— booked {book_qty}/{qty} @ {exit_fill:.2f} net=₹{pnl_final:.0f}; "
              f"runner qty={keep_qty} with SL=entry (₹{entry:.2f}) toward tgt ₹{position['target']:.2f}")
        try:
            await _send_telegram(
                f"💰 Partial book {position['instrument']} {position['strike']}{position['type']}: "
                f"+₹{pnl_final:.0f} on {book_qty} qty. Runner {keep_qty} qty rides to ₹{position['target']:.2f}."
            )
        except Exception:
            pass

    async def _exit_position(self, position: dict, reason: str, current_price: float = None):
        if current_price is None:
            current_price = position.get("ltp", position["entry"])

        # Live position: place real exit order via AngelOne
        if position.get("is_live") and not TRADING["paper_trade"]:
            fill_price = await _executor.exit(
                position=position,
                reason=reason,
                current_price=current_price,
                telegram_fn=_send_telegram,
            )
            current_price = fill_price

        # Realistic exit: receive the bid (apply slippage), then charge full fee stack
        exit_quote = current_price
        vix_val = getattr(store, "india_vix", 15.0)
        vix_val = vix_val if isinstance(vix_val, (int, float)) and vix_val > 0 else 15.0
        exit_fill  = apply_slippage(current_price, "sell", vix=vix_val) if not position.get("is_live") else current_price
        breakdown  = realistic_pnl(position["entry"], exit_fill, position["quantity"])
        pnl_raw    = breakdown["pnl_raw"]
        pnl_final  = breakdown["pnl_final"]
        fees_total = breakdown["fees"]["total"]
        slippage_cost = round((exit_quote - exit_fill) * position["quantity"], 2)

        store.realized_pnl   += pnl_final
        store.cumulative_pnl += pnl_final
        store.remove_position(position["instrument"], position["strike"], position["type"])

        exit_time = datetime.now(IST).isoformat()
        trade_db_id = position.get("trade_db_id")
        if trade_db_id:
            await db.update_trade_exit(
                trade_db_id=trade_db_id,
                exit_time=exit_time,
                exit_price=exit_fill,
                exit_reason=reason,
                pnl_raw=pnl_raw,
                pnl_final=pnl_final,
                fees_total=fees_total,
                slippage_cost=slippage_cost,
            )
        else:
            # fallback: position entered before this fix — insert a full record
            await db.insert_trade({
                "trade_type":  "paper",
                "instrument":  position["instrument"],
                "action":      position.get("action", f"BUY_{position['type']}"),
                "strike":      position["strike"],
                "expiry":      position["expiry"],
                "entry_time":  position["entry_time"],
                "entry_price": position["entry"],
                "exit_time":   exit_time,
                "exit_price":  exit_fill,
                "exit_reason": reason,
                "quantity":    position["quantity"],
                "pnl_raw":     pnl_raw,
                "pnl_final":   pnl_final,
                "signal_id":   position.get("signal_id"),
            })
        print(f"[trader] EXIT {position['instrument']} {position['strike']}{position['type']} "
              f"@ {exit_fill:.2f} (quoted {exit_quote:.2f}) | raw=Rs{pnl_raw:.0f} "
              f"fees=Rs{fees_total:.0f} slip=Rs{slippage_cost:.0f} net=Rs{pnl_final:.0f} [{reason}]")

    async def sl_monitor_loop(self):
        """
        Runs every 60 seconds independently of the 5-min market loop.
        Fetches fresh option LTPs and exits any position that has hit SL or target.
        This prevents up-to-5-minute delay between SL breach and exit.
        """
        while True:
            await asyncio.sleep(60)
            if not store.positions:
                continue
            try:
                ltps = await asyncio.get_running_loop().run_in_executor(
                    None, fetch_option_ltps, store.positions
                )
                for pos in list(store.positions):
                    key = f"{pos['instrument']}_{pos['strike']}_{pos['type']}"
                    ltp = ltps.get(key)
                    if not ltp:
                        continue
                    pos["ltp"] = ltp
                    pos["pnl"] = round((ltp - pos["entry"]) * pos["quantity"], 2)
                    store.option_prices[key] = ltp
                    if ltp <= pos["sl"]:
                        print(f"[sl_monitor] SL HIT {pos['instrument']} {pos['strike']}{pos['type']} "
                              f"ltp={ltp:.2f} sl={pos['sl']:.2f}")
                        await self._exit_position(pos, reason="SL", current_price=ltp)
                    elif ltp >= pos["target"]:
                        print(f"[sl_monitor] TARGET HIT {pos['instrument']} {pos['strike']}{pos['type']} "
                              f"ltp={ltp:.2f} tgt={pos['target']:.2f}")
                        await self._exit_position(pos, reason="TARGET", current_price=ltp)
                    else:
                        await self._maybe_partial_book(pos, ltp)
            except Exception as e:
                print(f"[sl_monitor] error: {e}")

    async def end_of_day(self):
        for pos in list(store.positions):
            await self._exit_position(pos, reason="EOD")

        summary = store.get_daily_summary()
        print(f"[trader] EOD Summary: {summary}")
        await _send_telegram(
            f"📈 MAP TRADE EOD\n"
            f"P&L=₹{summary['total']:,.0f}  Positions={summary['positions']}"
        )
        store.reset_daily()
        self.agent.reset_daily_context()
        self._recent_entries = []
        self._market_open = False
        self._daily_loss_breaker_hit = False
        self._profit_lock_engaged = False   # reset daily — else next day pins SLs at open
        self._expiries_cache = {}
        self._vix_cache = (0.0, 0.0)        # force a fresh VIX read tomorrow
