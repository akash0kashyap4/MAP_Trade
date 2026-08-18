# RAGI → MAP Trade — Rebrand Migration Guide

The project was renamed from **RAGI** to **MAP Trade**. The rename covers
deployment-coupled identifiers (systemd unit, script filenames, install paths,
env var names, the session cookie), so an existing install **will not pick up
the new names by itself** — it needs the one-time migration below.

Until you run it, an already-running instance keeps working off its old unit and
paths. Nothing breaks the moment you pull; it breaks only if you half-migrate
(for example, renaming the directory but leaving the old systemd unit pointing at
the old path). Do a full pass on each host.

---

## 1. What changed

### Files renamed

| Old | New |
|-----|-----|
| `deploy/ragi.service` | `deploy/map-trade.service` |
| `deploy/ragi.nginx` | `deploy/map-trade.nginx` |
| `deploy/android/start_ragi.sh` | `deploy/android/start_map_trade.sh` |
| `deploy/android/stop_ragi.sh` | `deploy/android/stop_map_trade.sh` |
| `deploy/android/status_ragi.sh` | `deploy/android/status_map_trade.sh` |
| `deploy/android/restart_ragi.sh` | `deploy/android/restart_map_trade.sh` |

### Identifiers renamed

| Kind | Old | New |
|------|-----|-----|
| systemd unit | `ragi.service` | `map-trade.service` |
| systemd timers | `ragi-token-refresh`, `ragi-claude-warmup` | `map-trade-token-refresh`, `map-trade-claude-warmup` |
| Install path (server) | `/root/Ragi_bot` | `/root/MAP_Trade` |
| Install path (Android) | `~/Ragi_bot` | `~/MAP_Trade` |
| Env var | `RAGI_DIR` | `MAP_TRADE_DIR` |
| Env var | `RAGI_BOT_ROOT` | `MAP_TRADE_ROOT` |
| Env var | `RAGI_CHART_DIR` | `MAP_TRADE_CHART_DIR` |
| Env var | `RAGI_REPORT_DIR` | `MAP_TRADE_REPORT_DIR` |
| Session cookie | `ragi_session` | `map_trade_session` |
| Health `service` field | `ragi-bot` | `map-trade` |
| Logger names | `ragi.main`, `ragi.runtime` | `map_trade.main`, `map_trade.runtime` |
| PID file | `pids/ragi.pid` | `pids/map_trade.pid` |
| Log file | `logs/ragi.log` | `logs/map_trade.log` |
| Termux:Boot script | `~/.termux/boot/start_ragi.sh` | `~/.termux/boot/start_map_trade.sh` |

### Deliberately **not** changed

- Past git branch names quoted in `docs/REMEDIATION_BLUEPRINT.md`
  (`claude/ragi-bot-*`) — those branches really are named that; rewriting them
  would make the document wrong.
- The old domain in `CHANGES_CONTEXT.md` (`ragi.rajwork.online`) — it is a
  historical note about a migration that already happened.
- The database file name (`data_store/trading_bot.db`) and every table/column in
  it. **No schema change, no data migration.** Your trade history carries over
  untouched.

---

## 2. Server (systemd + nginx)

Run as root on the EC2/VPS host.

```bash
# 1. Stop the old service
sudo systemctl stop ragi
sudo systemctl disable ragi

# 2. Move the install directory
mv /root/Ragi_bot /root/MAP_Trade
cd /root/MAP_Trade

# 3. Pull the rebranded code
git pull origin main

# 4. Install the new unit, remove the old one
sudo cp deploy/map-trade.service /etc/systemd/system/map-trade.service
sudo rm -f /etc/systemd/system/ragi.service
sudo systemctl daemon-reload
sudo systemctl enable map-trade
sudo systemctl start map-trade

# 5. Verify
sudo systemctl status map-trade
curl -s localhost:8000/health
```

`/health` must now report `"service": "map-trade"`. If you have monitoring or an
uptime check asserting `ragi-bot`, update it to `map-trade` — otherwise it will
alert on a healthy box.

**The venv path is baked into the unit.** `map-trade.service` runs
`/root/MAP_Trade/venv/bin/uvicorn`. If your venv lives elsewhere, edit
`WorkingDirectory`, the `PATH` line and `ExecStart` before starting.

### nginx

```bash
sudo cp deploy/map-trade.nginx /etc/nginx/sites-available/map-trade
sudo ln -sf /etc/nginx/sites-available/map-trade /etc/nginx/sites-enabled/map-trade
sudo rm -f /etc/nginx/sites-enabled/ragi /etc/nginx/sites-available/ragi
sudo nginx -t && sudo systemctl reload nginx
```

### Timers (only if you use them)

```bash
sudo systemctl disable --now ragi-token-refresh.timer ragi-claude-warmup.timer
sudo rm -f /etc/systemd/system/ragi-token-refresh.* /etc/systemd/system/ragi-claude-warmup.*
# re-create as map-trade-token-refresh / map-trade-claude-warmup, then:
sudo systemctl daemon-reload
```

---

## 3. Android / Termux (Moto G51)

The shell scripts derive their root from their own location
(`$SCRIPT_DIR/../..`), so they keep working whatever the clone directory is
called. Renaming it is still recommended so paths match the docs.

```bash
# 1. Stop bot + watchdog using the OLD script (still present pre-pull)
cd ~/Ragi_bot
bash deploy/android/stop_ragi.sh

# 2. Rename the clone and pull
cd ~
mv Ragi_bot MAP_Trade
cd ~/MAP_Trade
git pull origin main

# 3. Start with the new script
bash deploy/android/start_map_trade.sh
bash deploy/android/status_map_trade.sh
```

### Termux:Boot autostart

The boot script still points at the old path and filename — regenerate it:

```bash
rm -f ~/.termux/boot/start_ragi.sh
bash deploy/android/install_android.sh   # rewrites ~/.termux/boot/start_map_trade.sh
```

Or edit it by hand so it `cd`s to `~/MAP_Trade` and calls
`deploy/android/start_map_trade.sh`.

### Stale PID / log files

The old `pids/ragi.pid` and `logs/ragi.log` are simply no longer read. Delete
them once the new process is confirmed up:

```bash
rm -f deploy/android/pids/ragi.pid logs/ragi.log
```

Do **not** delete `ragi.pid` while the old process is still running — stop it
first (step 1), or you lose the handle needed to stop it cleanly.

---

## 4. Environment file

Rename these keys in your `.env` on every host. Old names are no longer read, so
a missed key silently falls back to its default (`data/charts`, `data/reports`)
rather than erroring — check for it.

```diff
-RAGI_BOT_ROOT=/home/user/Ragi_bot
+MAP_TRADE_ROOT=/home/user/MAP_Trade
-RAGI_CHART_DIR=...
+MAP_TRADE_CHART_DIR=...
-RAGI_REPORT_DIR=...
+MAP_TRADE_REPORT_DIR=...
-RAGI_DIR=...
+MAP_TRADE_DIR=...
```

If you set `DB_PATH` to an absolute path containing `Ragi_bot`, update it to the
new directory or the bot will create an **empty new database** and appear to have
lost all history:

```diff
-DB_PATH=/data/data/com.termux/files/home/Ragi_bot/data_store/trading_bot.db
+DB_PATH=/data/data/com.termux/files/home/MAP_Trade/data_store/trading_bot.db
```

---

## 5. Expected one-time effects

- **You will be logged out of the dashboard.** The cookie is now
  `map_trade_session`; the browser's old `ragi_session` cookie is ignored. Log in
  again — credentials are unchanged.
- **`journalctl -u ragi` stops working.** Use `journalctl -u map-trade`. Old logs
  remain under the old unit name in the journal; they are not rewritten.
- **Telegram messages now read `[MAP Trade]`** instead of `[Ragi]`.

---

## 6. Verify

```bash
curl -s localhost:8000/health          # "service":"map-trade"
systemctl is-active map-trade          # active          (server)
bash deploy/android/status_map_trade.sh # running        (Android)
```

Then open the dashboard: the tab title should read **MAP Trade — Trading
Terminal**, and the login page should show **MAP·TRADE**.

---

## 7. Rollback

The rename is code-only — no schema or data changed — so rollback is just
checking out the previous commit and restoring the old unit/paths:

```bash
cd /root/MAP_Trade && git log --oneline -5      # find the pre-rebrand commit
git checkout <pre-rebrand-sha>
mv /root/MAP_Trade /root/Ragi_bot
sudo cp /root/Ragi_bot/deploy/ragi.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now ragi
```

Your database is untouched either way.
