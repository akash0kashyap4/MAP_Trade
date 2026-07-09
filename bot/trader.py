from __future__ import annotations
import asyncio
from datetime import datetime, timedelta
from typing import Optional

import pytz

try:
    import yfinance as yf
    _YF_OK = True
except ImportError:
    _YF_OK = False

# curl_cffi browser impersonation — Yahoo blocks bare requests from AWS/datacenter IPs
try:
    from curl_cffi import requests as _cf_requests
    _YF_SESSION = _cf_requests.Session(impersonate="chrome")
except Exception:
    _YF_SESSION = None

from config import TRADING, INSTRUMENTS, LOT_SIZES, INITIAL_CAPITAL
from data.store import store
from data import database as db
from bot.risk import calc_quantity, calc_sl_price, calc_target_price, calc_trailing_sl, max_positions_reached
from bot.strategy import build_market_context, is_valid_trade_time
from bot.decision_log import DecisionLog
from bot.fees import apply_slippage, realistic_pnl
from groww.historical import (
    get_index_candles, get_live_option_from_chain, round_to_atm,
    get_india_vix, get_option_chain_analytics,
)
from groww.quotes import fetch_option_ltps
from groww.live_feed import start_feed, request_option_subscribe

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
    loop = asyncio.get_event_loop()
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
            _mk = lambda s: yf.Ticker(s, session=_YF_SESSION) if _YF_SESSION else yf.Ticker(s)
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

    async def premarket_analysis(self):
        store.ai_status = "analyzing"
        global_data = await _fetch_global_cues()
        # Fetch India VIX via Upstox (more reliable than yfinance)
        vix = await asyncio.get_event_loop().run_in_executor(None, get_india_vix)
        if vix and vix > 0:
            global_data["india_vix"] = vix
            store.india_vix = vix
        plan = await self.agent.premarket_analysis(global_data)
        store.premarket_bias = plan
        store.ai_status = "waiting"
        print(f"[trader] Day plan: {plan.get('bias')} | Risk: {plan.get('risk_level')} | VIX={vix}")
        await _send_telegram(f"📊 Ragi Day Plan: {plan.get('bias')} | Risk: {plan.get('risk_level')}\n{plan.get('reasoning','')}")
        self._market_open = True

    def _check_market_open(self) -> bool:
        from datetime import datetime
        from config import is_market_day
        now = datetime.now(IST)
        if not is_market_day(now.date()):
            return False
        mins = now.hour * 60 + now.minute
        return 9 * 60 + 15 <= mins <= 15 * 60 + 30

    async def market_loop_tick(self):
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

        # Refresh India VIX every tick
        vix = await asyncio.get_event_loop().run_in_executor(None, get_india_vix)
        if vix and vix > 0:
            store.india_vix = vix

        try:
            # Refresh option LTPs for all open positions
            if store.positions:
                ltps = await asyncio.get_event_loop().run_in_executor(
                    None, fetch_option_ltps, store.positions
                )
                for pos in store.positions:
                    key = f"{pos['instrument']}_{pos['strike']}_{pos['type']}"
                    if key in ltps:
                        pos["ltp"] = ltps[key]
                        pos["pnl"] = round((ltps[key] - pos["entry"]) * pos["quantity"], 2)
                        store.option_prices[key] = ltps[key]
                        if ltps[key] <= pos["sl"]:
                            await self._exit_position(pos, reason="SL", current_price=ltps[key])
                        elif ltps[key] >= pos["target"]:
                            await self._exit_position(pos, reason="TARGET", current_price=ltps[key])

            for instrument in ["NIFTY", "BANKNIFTY", "SENSEX"]:
                await self._process_instrument(instrument, time_str)

            # AI-driven trailing SL / exit — ask Claude what to do with each open position
            for position in list(store.positions):
                current_price = store.option_prices.get(
                    f"{position['instrument']}_{position['strike']}_{position['type']}", position["ltp"]
                )
                if current_price <= position["entry"]:
                    continue  # only trail once in profit
                try:
                    trail = await self.agent.check_trailing_sl(position, current_price)
                except Exception as e:
                    print(f"[trader] trailing SL AI error: {e}")
                    continue
                t_action = trail.get("action", "HOLD")
                if t_action == "MOVE_SL":
                    new_sl = trail.get("new_sl")
                    if isinstance(new_sl, (int, float)) and new_sl > position["sl"] and new_sl < current_price:
                        print(f"[trader] AI trailing SL {position['instrument']} {position['strike']}{position['type']}: "
                              f"{position['sl']:.2f} → {new_sl:.2f} (ltp={current_price:.2f}) | {trail.get('reason','')}")
                        position["sl"] = round(float(new_sl), 2)
                elif t_action == "EXIT":
                    print(f"[trader] AI exit signal {position['instrument']} {position['strike']}{position['type']} | {trail.get('reason','')}")
                    await self._exit_position(position, reason="AI_EXIT", current_price=current_price)

        except Exception as e:
            import traceback
            print(f"[trader] tick error at {time_str}: {e}\n{traceback.format_exc()}")

        finally:
            store.ai_status = "in_trade" if store.positions else "waiting"

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

        h, m = map(int, time_str.split(":"))
        current_mins = h * 60 + m
        current_vix = getattr(store, "india_vix", 0)

        # Detect expiry day (Nifty=Thu, BankNifty=Wed, Sensex=Fri) — info only, AI decides
        now_dt = datetime.now(IST)
        weekday = now_dt.weekday()
        _expiry_weekdays = {"NIFTY": 3, "BANKNIFTY": 2, "SENSEX": 4}
        is_expiry_day = weekday == _expiry_weekdays.get(instrument, 3)

        # Fetch option chain analytics (PCR, IV, OI, max pain) for current nearest expiry
        from groww.historical import get_live_option_from_chain as _glo
        step = 100 if instrument == "SENSEX" else 50
        # Quick expiry lookup via chain scan (reuse cached if same day)
        _today_str = date_str
        _expiry_cache_key = f"{instrument}_{_today_str}"
        nearest_expiry = self._expiries_cache.get(_expiry_cache_key)
        if not nearest_expiry:
            # Scan next 10 days for valid expiry
            from datetime import date as _date
            _td = _date.today()
            from config import NSE_HOLIDAYS
            import urllib.parse, requests as _req
            from config import BASE_URL, UPSTOX_TOKEN
            _enc = urllib.parse.quote(instrument_key, safe="")
            for _days in range(0, 10):
                _cand = (_td + timedelta(days=_days)).strftime("%Y-%m-%d")
                try:
                    _r = _req.get(f"{BASE_URL}/option/chain?instrument_key={_enc}&expiry_date={_cand}",
                                  headers={"Authorization": f"Bearer {UPSTOX_TOKEN}", "Accept": "application/json"},
                                  timeout=8)
                    if _r.status_code == 200 and _r.json().get("data"):
                        nearest_expiry = _cand
                        self._expiries_cache[_expiry_cache_key] = nearest_expiry
                        break
                except Exception:
                    pass

        chain_analytics = {}
        if nearest_expiry:
            chain_analytics = await asyncio.get_event_loop().run_in_executor(
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
        if action in ("BUY_CE", "BUY_PE"):
            option_type = "CE" if action == "BUY_CE" else "PE"
            step = 100 if instrument == "SENSEX" else 50

            opt_data = await asyncio.get_event_loop().run_in_executor(
                None, get_live_option_from_chain, instrument_key, spot_price, option_type, step
            )
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
            entry_price = apply_slippage(entry_price, "buy")
            log.info("Slippage", f"quoted={entry_quote} -> fill@ask={entry_price}",
                     quoted=entry_quote, fill=entry_price)

            quantity = calc_quantity(instrument)
            trade_cost = round(entry_price * quantity, 2)

            if trade_cost > store.capital_available:
                msg = f"Insufficient capital - need ₹{trade_cost:,.0f}, have ₹{store.capital_available:,.0f}"
                log.guard_block("Capital", msg)
                log.finalize("SKIP", "insufficient_capital")
                self._log_skip(instrument, msg, time_str, log)
                return
            log.guard_pass("Capital", f"cost=₹{trade_cost:,.0f} within budget")

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
                # REAL TRADING EXECUTION VIA GROWW
                try:
                    from groww.orders import place_market_order
                    groww_symbol = opt_key # Note: Groww may expect a different symbol format
                    order_id = place_market_order(groww_symbol, quantity, "BUY")
                    
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
                        "order_id":       order_id,
                    }
                    store.add_position(position)
                    log.finalize("ENTERED_REAL", f"{action} {atm_strike}{option_type} @ {entry_price:.2f}",
                                 sl=sl, target=target, order_id=order_id)
                    print(f"[trader] REAL {action} {atm_strike}{option_type} @ {entry_price:.2f} | SL={sl:.2f} TGT={target:.2f}")
                except Exception as e:
                    print(f"[trader] Failed to place REAL order via Groww: {e}")
            # AI returned NO_TRADE / HOLD - record the decision trail anyway so we can review later
            log.finalize("NO_TRADE", decision.get("reasoning", "")[:120])
            for line in log.summary_lines():
                print(line)

        if action == "EXIT_ALL":
            for pos in list(store.positions):
                if pos["instrument"] == instrument:
                    await self._exit_position(pos, reason="ai_exit")

    async def _exit_position(self, position: dict, reason: str, current_price: float = None):
        if current_price is None:
            current_price = position.get("ltp", position["entry"])

        # Realistic exit: receive the bid (apply slippage), then charge full fee stack
        exit_quote = current_price
        exit_fill  = apply_slippage(current_price, "sell")
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
                ltps = await asyncio.get_event_loop().run_in_executor(
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
            except Exception as e:
                print(f"[sl_monitor] error: {e}")

    async def end_of_day(self):
        for pos in list(store.positions):
            await self._exit_position(pos, reason="EOD")

        summary = store.get_daily_summary()
        print(f"[trader] EOD Summary: {summary}")
        await _send_telegram(
            f"📈 Ragi EOD\n"
            f"P&L=₹{summary['total']:,.0f}  Positions={summary['positions']}"
        )
        store.reset_daily()
        self.agent.reset_daily_context()
        self._recent_entries = []
        self._market_open = False
        self._daily_loss_breaker_hit = False
        self._expiries_cache = {}
