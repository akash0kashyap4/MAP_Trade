# MAP Trade — Mobile Operations Guide

## Quick Reference

### Start / Stop / Status

```bash
# Start the bot
bash deploy/android/start_map_trade.sh

# Stop the bot  
bash deploy/android/stop_map_trade.sh

# Restart
bash deploy/android/restart_map_trade.sh

# Full status check
bash deploy/android/status_map_trade.sh

# Quick health check
curl -s localhost:8000/health/detailed | python -m json.tool
```

### Logs

```bash
# Live log stream
tail -f logs/map_trade.log

# Last 50 lines
tail -50 logs/map_trade.log

# Search for errors
grep -i "error\|exception\|fail" logs/map_trade.log | tail -20

# Runtime log (AI provider activity)
tail -f logs/runtime.log

# Watchdog log
tail -f logs/watchdog.log
```

### Watchdog (Auto-Restart)

```bash
# Enable watchdog
bash deploy/android/watchdog.sh &

# Check watchdog status
bash deploy/android/status_map_trade.sh

# Stop watchdog (also stopped when you run stop_map_trade.sh)
kill $(cat deploy/android/pids/watchdog.pid)
```

### Database

```bash
# Create backup
bash deploy/android/backup_db.sh

# List backups
ls -lh data_store/backups/

# Restore backup (stop bot first!)
bash deploy/android/stop_map_trade.sh
cp data_store/backups/trading_bot_YYYYMMDD_HHMMSS.db data_store/trading_bot.db
bash deploy/android/start_map_trade.sh

# Database size
du -h data_store/trading_bot.db

# Quick DB query
sqlite3 data_store/trading_bot.db "SELECT COUNT(*) FROM trades;"
```

## Troubleshooting

### Bot is not running

```bash
# Check process
ps aux | grep python

# Check if port is busy
ss -tlnp | grep 8000

# Check PID file
cat deploy/android/pids/map_trade.pid

# Manual start (foreground, for debugging)
source venv/bin/activate
python main.py
```

### API / broker connectivity issues

```bash
# Test internet connectivity
ping -c 3 api.kite.trade 2>/dev/null || curl -s https://httpbin.org/ip

# Check DNS
nslookup api.angelbroking.com

# Health endpoint shows broker status
curl -s localhost:8000/health/detailed | python -m json.tool
```

### Dashboard not loading

```bash
# Verify bot is running
curl -s localhost:8000/health

# Check if you're hitting the right port
grep APP_PORT .env

# Try from phone browser: http://localhost:8000
# Try from same-network device: http://<phone-ip>:8000
```

### SQLite locked / database errors

```bash
# Stop the bot
bash deploy/android/stop_map_trade.sh

# Remove lock files (safe when bot is stopped)
rm -f data_store/trading_bot.db-wal
rm -f data_store/trading_bot.db-shm

# Verify DB integrity
sqlite3 data_store/trading_bot.db "PRAGMA integrity_check;"

# Restart
bash deploy/android/start_map_trade.sh
```

### High memory / CPU

```bash
# Check memory usage
cat /proc/$(cat deploy/android/pids/map_trade.pid)/status | grep VmRSS

# If using Ollama, check its memory
ps aux | grep ollama

# Switch to cloud AI to save local resources
# Edit .env: AI_PROVIDER=claude
```

### After phone reboot

```bash
# If Termux:Boot is installed, bot should auto-start after 15 seconds
# If not:
termux-wake-lock
cd ~/MAP_Trade
bash deploy/android/start_map_trade.sh
bash deploy/android/watchdog.sh &
```

## Health Checks

### Automated (via watchdog)
The watchdog checks every 60 seconds if the bot process is alive and restarts it if needed.

### Manual (via HTTP)
```bash
# Simple health
curl localhost:8000/health

# Detailed health (db, llm, scheduler, positions, pnl)
curl localhost:8000/health/detailed

# Full trading status (authenticated)
curl -b "map_trade_session=<your-token>" localhost:8000/api/status
```

### What each health field means

| Field | Meaning |
|-------|---------|
| `status` | "ok" = all good, "degraded" = something wrong |
| `trading_mode` | "paper" or "live" |
| `bot_paused` | true if operator paused the bot |
| `feed_status` | "live" = receiving market data |
| `ai_status` | "waiting" / "analyzing" / "in_trade" / "paused" |
| `db` | "ok" or error message |
| `llm_provider` | which AI provider is active |
| `llm_available` | whether the AI provider is reachable |
| `positions_open` | number of open trading positions |
| `last_tick` | time of last market analysis cycle |

## Daily Routine

1. **Morning (before 8:15 IST):** Ensure bot is running — it handles news scan (08:15), premarket (08:30) automatically
2. **During market hours:** Monitor via dashboard or `/health/detailed`
3. **After market (15:20+):** Bot auto-closes positions at EOD, generates report at 15:45
4. **Weekly:** Run `bash deploy/android/backup_db.sh`
