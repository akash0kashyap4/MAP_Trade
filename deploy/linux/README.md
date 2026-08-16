# Ragi Bot — Linux Mint / Ubuntu 24/7 Deployment

Host the bot on your laptop or desktop instead of a phone. Tested on
Linux Mint 21+ and Ubuntu 22.04+ (any Debian-family distro with systemd
should work).

## What you get

- Python venv with all dependencies (`install_linux.sh`)
- Skeleton `.env` you fill with credentials
- Manual start/stop/restart/status scripts (PID-tracked, no root)
- A watchdog script for restart-on-crash
- A **systemd user service** for real 24/7 operation (auto-start on boot,
  auto-restart on crash, no sudo needed once installed)
- Daily SQLite backup script (`backup_db.sh`)

## Quick start

```bash
# 1. Clone (skip if you already have the repo)
sudo apt install -y git
git clone https://github.com/akash0kashyap4/ragi_bot.git ~/Ragi_bot
cd ~/Ragi_bot

# 2. Install Python venv + dependencies
bash deploy/linux/install_linux.sh

# 3. Fill in credentials
nano .env
#   BOT_USERNAME / BOT_PASSWORD / SESSION_SECRET
#   ANTHROPIC_API_KEY, GROWW_API_KEY, TELEGRAM_*  (as applicable)

# 4. Smoke test manually
bash deploy/linux/start_ragi.sh
tail -f logs/ragi.log
# open http://localhost:8000  → login with BOT_USERNAME / BOT_PASSWORD
bash deploy/linux/stop_ragi.sh

# 5. Install the systemd user service (real 24/7)
bash deploy/linux/install_systemd_user.sh
```

After step 5 the bot starts on every boot and restarts within 10 s if it
crashes. `loginctl enable-linger` (run by the installer) lets it start
even when nobody is logged in.

## Management commands

| Action              | Manual scripts                                | systemd user service                          |
|---------------------|-----------------------------------------------|-----------------------------------------------|
| Start               | `bash deploy/linux/start_ragi.sh`             | `systemctl --user start ragi.service`         |
| Stop                | `bash deploy/linux/stop_ragi.sh`              | `systemctl --user stop ragi.service`          |
| Restart             | `bash deploy/linux/restart_ragi.sh`           | `systemctl --user restart ragi.service`       |
| Status              | `bash deploy/linux/status_ragi.sh`            | `systemctl --user status ragi.service`        |
| Logs                | `tail -f logs/ragi.log`                       | `journalctl --user -u ragi.service -f`        |
| Watchdog (fallback) | `nohup bash deploy/linux/watchdog.sh &`       | not needed — systemd handles restart          |
| Backup DB           | `bash deploy/linux/backup_db.sh`              | same                                          |

Use **either** the systemd service **or** the manual + watchdog combo —
not both at once (they'll fight over the PID).

## Recommended laptop tweaks (24/7 host)

1. **Do not sleep on lid close.** In `/etc/systemd/logind.conf` set:
   ```
   HandleLidSwitch=ignore
   HandleLidSwitchExternalPower=ignore
   HandleLidSwitchDocked=ignore
   ```
   then `sudo systemctl restart systemd-logind`.

2. **Disable suspend/hibernate entirely** (paranoid but bullet-proof):
   ```bash
   sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
   ```

3. **Keep the network up** — the systemd unit already waits on
   `network-online.target`. If you use Wi-Fi, prefer `nmcli` with
   auto-connect enabled.

4. **Auto-nightly DB backup** via cron:
   ```bash
   crontab -e
   # add:
   30 21 * * *  /bin/bash $HOME/Ragi_bot/deploy/linux/backup_db.sh >> $HOME/Ragi_bot/logs/backup.log 2>&1
   ```

5. **Access from your phone on the same Wi-Fi:** find the laptop's LAN
   IP with `ip -4 addr show | grep inet` and open
   `http://<laptop-ip>:8000` from any device.

## Trading safety

- Default is **PAPER** trading (`TRADING_MODE=paper`).
- Only set `TRADING_MODE=live` after confirming AngelOne creds and
  reviewing risk knobs in `config.py` (max daily loss, max positions,
  fallback SL/target).
- The daily-loss circuit breaker (`max_daily_loss=5000`) is always on.

## Troubleshooting

**Bot won't start**
```bash
tail -50 logs/ragi.log
ss -tlnp | grep 8000        # is another process on the port?
cat .env | grep -v '^#'     # is .env actually filled in?
```

**Port already in use** — either kill the other process or change
`APP_PORT` in `.env` and restart.

**systemd unit fails immediately** — check `journalctl --user -u ragi.service -n 100`.
Common causes: `EnvironmentFile` path wrong (repo not at `$HOME/Ragi_bot`)
or venv missing (`install_linux.sh` not run yet).

**Database locked** — stop the bot, `sqlite3 data_store/trading_bot.db "PRAGMA integrity_check;"`,
restart. Restore from `data_store/backups/` if corrupted.
