# MAP Trade — Android/Termux Deployment Guide

## Target Device

Motorola Moto G51 5G (or any Android device with Termux)

- **Chipset:** Snapdragon 480+ / Dimensity 700+
- **RAM:** 4-6 GB
- **Network:** Mobile data (outbound only, no static IP needed)
- **Runtime:** Termux (Linux userspace, no root)

## Prerequisites

1. **Termux** — Install from [F-Droid](https://f-droid.org/packages/com.termux/) (NOT Google Play — that version is outdated)
2. **Termux:Boot** (optional) — For auto-start after phone reboot. Install from F-Droid.
3. **Termux:API** (optional) — For Termux wake lock and notifications.

## Quick Setup

```bash
# 1. Clone the repository
pkg install git
git clone https://github.com/akash0kashyap4/MAP_Trade.git ~/MAP_Trade
cd ~/MAP_Trade

# 2. Run the installer
bash deploy/android/install_android.sh

# 3. Configure credentials
nano .env
# Set: BOT_USERNAME, BOT_PASSWORD, SESSION_SECRET, API keys

# 4. Start the bot
bash deploy/android/start_map_trade.sh
```

## Management Commands

| Action | Command |
|--------|---------|
| Start bot | `bash deploy/android/start_map_trade.sh` |
| Stop bot | `bash deploy/android/stop_map_trade.sh` |
| Restart bot | `bash deploy/android/restart_map_trade.sh` |
| Check status | `bash deploy/android/status_map_trade.sh` |
| Enable watchdog | `bash deploy/android/watchdog.sh &` |
| Backup database | `bash deploy/android/backup_db.sh` |
| View logs | `tail -f logs/map_trade.log` |
| Check health (HTTP) | `curl localhost:8000/health/detailed` |

## Watchdog (Auto-Restart)

The watchdog monitors the bot process and restarts it if it crashes:

```bash
bash deploy/android/watchdog.sh &
```

Safety limits:
- Max 5 restarts in 30 minutes, then enters safe mode
- 5-minute cooldown between restarts
- Requires manual restart after hitting safe mode

## Restore Database from Backup

```bash
# Stop the bot first
bash deploy/android/stop_map_trade.sh

# List available backups
ls -la data_store/backups/

# Restore a specific backup
cp data_store/backups/trading_bot_20260814_120000.db data_store/trading_bot.db

# Restart
bash deploy/android/start_map_trade.sh
```

## Local AI (Ollama) Setup

For fully offline AI analysis on the phone:

```bash
# Install Ollama for Termux (community build)
# Check https://github.com/ollama/ollama for ARM64 builds

# Pull a lightweight model suitable for 4GB RAM:
ollama pull qwen2:1.5b      # ~1 GB, fastest
# or
ollama pull gemma2:2b        # ~1.6 GB
# or
ollama pull phi3:mini         # ~2.3 GB, best quality

# Update .env:
# AI_PROVIDER=ollama
# OLLAMA_URL=http://localhost:11434
# OLLAMA_MODEL=qwen2:1.5b
```

**Important:** Do NOT use `llama3.1` (8B, ~4.7 GB) — it will exceed the phone's RAM.

The LLM is used for market analysis, news classification, and signal explanation only. It NEVER directly executes trades.

## Network Considerations

- The bot uses **outbound HTTP only** — no incoming connections needed
- Mobile data works fine; no static IP or port forwarding required
- Brief disconnects are handled with retry/backoff in the data fetchers
- Access the dashboard from the phone's browser at `http://localhost:8000`
- To access from another device on the same network, use the phone's local IP

## Battery & Performance

- **Wake lock:** The start script acquires a Termux wake lock to prevent Android from killing the process
- **Battery saver:** Add Termux to battery optimization exemptions in Android Settings
- **Background execution:** On some Android versions, you may need to lock Termux in the recent apps tray
- **Data usage:** Minimal — REST API calls are typically a few KB each

## Android Settings (Recommended)

1. **Battery:** Settings > Battery > Unrestricted for Termux
2. **Background:** Lock Termux in recent apps (prevents Android from killing it)
3. **Storage:** Ensure at least 1 GB free for database and logs
4. **Auto-start:** Install Termux:Boot from F-Droid

## Trading Safety

- **Default mode is always PAPER trading** — set `TRADING_MODE=paper` in `.env`
- Live trading requires explicit `TRADING_MODE=live` AND AngelOne credentials
- All risk controls (max loss, position limits, SL, profit lock) are preserved
- The bot will NOT auto-enable live trading during migration
- Emergency square-off is available from the dashboard

## Troubleshooting

### Bot won't start
```bash
# Check logs
tail -20 logs/map_trade.log

# Check if port is in use
ss -tlnp | grep 8000

# Verify .env is loaded
cat .env | grep -v "^#" | grep -v "^$"
```

### Database locked errors
```bash
# Stop the bot
bash deploy/android/stop_map_trade.sh

# Check for stale lock files
ls -la data_store/trading_bot.db*

# Remove WAL/SHM files (safe if bot is stopped)
rm -f data_store/trading_bot.db-wal data_store/trading_bot.db-shm

# Restart
bash deploy/android/start_map_trade.sh
```

### High memory usage
```bash
# Check bot memory
bash deploy/android/status_map_trade.sh

# If using Ollama, consider a smaller model
# Edit .env: OLLAMA_MODEL=qwen2:1.5b
```

### Phone overheating
- Reduce polling frequency (the default 10s/60s intervals are reasonable)
- Switch to cloud AI provider instead of local Ollama
- Close other apps
