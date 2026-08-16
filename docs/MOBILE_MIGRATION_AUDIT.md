# MAP TRADE Bot — Mobile Migration Audit (Moto G51 5G)

**Date:** 2026-08-14
**Target Device:** Motorola Moto G51 5G (Snapdragon 480+, 4/6 GB RAM, Android)
**Runtime:** Termux (Linux userspace, no root)
**Network:** Mobile data (outbound only, no static IP, no inbound)

---

## 1. Hardcoded VPS Paths

| File | Line | Issue | Solution |
|------|------|-------|----------|
| `deploy/map_trade.service` | 8,9,14 | `WorkingDirectory=/root/Ragi_bot`, `PATH=/root/Ragi_bot/venv/bin`, `ExecStart=/root/Ragi_bot/...` | VPS-only file; kept as-is. Android uses `deploy/android/` scripts with dynamic `MAP_TRADE_DIR` |
| `deploy.sh` | 6 | `cd /home/user/Ragi_bot` | VPS-only script; kept as-is. Android uses `deploy/android/start_map_trade.sh` |

## 2. systemd / Service Assumptions

| File | Issue | Solution |
|------|-------|----------|
| `deploy/map_trade.service` | systemd unit — unavailable on Termux | Keep for VPS. Android uses PID-file + watchdog shell scripts |
| `deploy.sh` | Assumes systemd restart | Keep for VPS. Android scripts handle restart independently |

## 3. Docker Assumptions

None found. The project does not use Docker.

## 4. Root-Only Commands

| File | Issue | Solution |
|------|-------|----------|
| `deploy/map_trade.service` | `User=root` | VPS-only. Android scripts run as the Termux user (no root needed) |

## 5. PostgreSQL Dependencies

| File | Issue | Solution |
|------|-------|----------|
| `data/database.py` | Dual-backend: SQLite (default) + PostgreSQL via `DATABASE_URL` | SQLite is default and works on Android. No change needed |
| `requirements.txt` | `asyncpg>=0.29.0` | Optional; only used if `DATABASE_URL` is set. Can skip install on Android if not needed |

## 6. SQLite Usage

| File | Issue | Solution |
|------|-------|----------|
| `config/__init__.py:117` | `DB_PATH = os.getenv("DB_PATH", "trading_bot.db")` — relative path | Already configurable via env var. Android `.env` sets absolute path under `$MAP_TRADE_DIR/data/` |
| `data/database.py` | No `timeout` on SQLite connections | Add `timeout=30` to prevent locking issues on constrained device |
| `data/database.py` | No WAL mode | Enable WAL for better concurrent read/write on mobile |
| `data/database.py` | No parent directory creation for DB path | Add `os.makedirs(parent, exist_ok=True)` |

## 7. Cron Assumptions

None. The project uses APScheduler (`AsyncIOScheduler`) in-process, not system cron. This is fully compatible with Termux.

## 8. Environment Variable Handling

| File | Issue | Solution |
|------|-------|----------|
| `config/__init__.py` | `load_dotenv()` at import time — correct | Works on Termux |
| `.env.example` | Missing `DEPLOYMENT_TARGET`, `APP_HOST`, `APP_PORT`, `LOG_DIR`, `DATA_DIR` | Add these new settings |
| `config/runtime.py` | `OLLAMA_MODEL` defaults to `llama3.1` | Too large for Moto G51. Make configurable, document smaller models |

## 9. Absolute Paths

| File | Issue | Solution |
|------|-------|----------|
| `config/runtime.py:17` | `_REPO_ROOT = Path(__file__).resolve().parent.parent` | Dynamic — OK |
| `config/runtime.py:18` | `_LOG_DIR = _REPO_ROOT / "logs"` | Works but should be configurable via `LOG_DIR` env var |
| `main.py:39` | `BASE_DIR = Path(__file__).parent` | Dynamic — OK |

## 10. Subprocess Commands

None found that would fail on Android/Termux. The AI providers use `requests` HTTP calls or subprocess for CLI tools (`claude`, `copilot`), which work in Termux if installed.

## 11. Ollama/LLM Integration

| File | Issue | Solution |
|------|-------|----------|
| `ai/providers/ollama.py` | Connects to `OLLAMA_URL` (default `localhost:11434`) | Works if Ollama is installed on Android or reachable on LAN |
| `config/runtime.py:53` | Default model `llama3.1` (8B params, ~4.7GB) | Too large for 4GB RAM phone. Document smaller models: `phi3:mini` (2.3GB), `gemma2:2b` (1.6GB), `qwen2:1.5b` (1GB) |
| LLM safety | LLM never directly executes trades | Confirmed: LLM outputs JSON signals; deterministic risk engine + guards decide execution |

## 12. Broker API Integrations

| Component | Status |
|-----------|--------|
| Groww API (`groww/`) | REST/HTTP — works on mobile data |
| AngelOne SmartAPI (`angelone/`) | REST/HTTP — works on mobile data |
| yfinance (`data/yfsession.py`) | REST/HTTP via `curl_cffi` — works on mobile data |
| Telegram Bot API | REST/HTTP — works on mobile data |

All broker integrations are outbound HTTP. No inbound connectivity required.

## 13. Schedulers / Background Workers

| Component | Details | Android Compatibility |
|-----------|---------|----------------------|
| APScheduler `AsyncIOScheduler` | In-process, timezone-aware cron jobs | Fully compatible |
| `trader.sl_monitor_loop()` | Async infinite loop (60s interval) | Compatible |
| `groww.live_feed.start_feed()` | Async polling loop (10s interval) | Compatible |
| SSE broadcast | In-process push to connected clients | Compatible |

## 14. Web Server Configuration

| File | Issue | Solution |
|------|-------|----------|
| `deploy/map_trade.nginx` | nginx reverse proxy | Not needed on Android (direct uvicorn access) |
| `main.py:325` | `host="0.0.0.0", port=8000` | Make configurable: `APP_HOST`, `APP_PORT` |

## 15. Logging and Log Rotation

| File | Issue | Solution |
|------|-------|----------|
| `config/runtime.py` | `RotatingFileHandler` to `logs/runtime.log`, 2MB, 3 backups | Good — bounded. Make `LOG_DIR` configurable |
| `main.py` | `logging.basicConfig` to stdout only | Fine for Termux terminal; logs can be redirected to file by start script |

## 16. Database Locking / Concurrency

| Issue | Risk | Solution |
|-------|------|----------|
| Multiple `aiosqlite.connect()` calls per operation | Each opens/closes connection — no pool | Add `timeout=30` for busy-wait on locks |
| No WAL mode | Default journal mode blocks readers during writes | Enable WAL mode on init |
| Single-process architecture | Low concurrency risk | Acceptable for mobile |

## 17. Restart / Recovery Behavior

| Issue | Solution |
|-------|----------|
| systemd `Restart=always` unavailable | Android watchdog script with PID monitoring |
| `trader.recover_active_positions()` | Already handles DB-based position recovery on restart — good |
| In-memory state (store, sessions) | Volatile; acceptable for trading bot (positions recovered from DB) |

## 18. Network Resilience

| Component | Current Handling | Needed |
|-----------|-----------------|--------|
| yfinance calls | `try/except` with empty returns | Add retry with backoff for mobile disconnects |
| Groww API | `try/except` | Adequate |
| Telegram | `try/except` | Adequate |
| AngelOne | `try/except` | Adequate |
| DNS resolution | `socket.getaddrinfo` IPv4 override | Compatible |

## 19. Trading Safety Controls (MUST PRESERVE)

All verified present and must NOT be weakened:

- [x] Max daily loss circuit breaker (`TRADING["max_daily_loss"]`)
- [x] Max position count (`TRADING["max_positions"]`)
- [x] Per-trade risk cap (`TRADING["max_risk_per_trade"]`)
- [x] Stop loss on every position
- [x] Consecutive-loss cooldown (`consecutive_loss_limit` + `cooldown_duration_minutes`)
- [x] Session profit lock (`session_profit_lock`)
- [x] Paper/live mode separation (`TRADING["paper_trade"]`)
- [x] Duplicate position prevention (same instrument+direction check)
- [x] Correlated-entry guard (cross-index same-direction within 5 min)
- [x] API failure handling (all broker calls wrapped in try/except)
- [x] Market hours validation (`is_market_day()`, `_check_market_open()`)
- [x] Emergency square-off endpoint
- [x] Live mode requires explicit confirmation phrase ("GO LIVE")

## 20. Performance Considerations for Moto G51

| Concern | Mitigation |
|---------|------------|
| 4-6 GB RAM | Avoid large models; bound in-memory caches; no unnecessary imports |
| CPU (Snapdragon 480+) | Polling intervals already reasonable (10s feed, 60s SL monitor, 5m ticks) |
| Storage (eMMC) | SQLite WAL mode reduces writes; bounded log rotation |
| Battery | No aggressive polling beyond existing intervals |
| Mobile data usage | yfinance + REST API calls are lightweight (~few KB per request) |

---

## Summary of Required Changes

1. **Configuration**: Add `DEPLOYMENT_TARGET`, `APP_HOST`, `APP_PORT`, `LOG_DIR`, `DATA_DIR`, `TRADING_MODE` env vars
2. **Database**: Add WAL mode, connection timeout, parent directory creation, configurable path
3. **Logging**: Make `LOG_DIR` configurable via env var
4. **Web server**: Make host/port configurable
5. **LLM**: Document appropriate small models for Moto G51
6. **Process management**: Create Termux-compatible start/stop/watchdog scripts
7. **Safety**: Default `TRADING_MODE=paper`, never auto-enable live trading
8. **Network**: Add basic retry for critical data fetches on unstable mobile connections
9. **Health monitoring**: Add lightweight health check endpoint and CLI script
