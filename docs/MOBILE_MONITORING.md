# Ragi Bot — LAN Dashboard Monitoring

Monitor your Ragi Bot running on a Moto G51 (or any Android/Termux device) from a laptop or desktop on the same local network.

## How It Works

The bot binds to `0.0.0.0` (all network interfaces), so any device on the same Wi-Fi or LAN can reach the dashboard using the phone's local IP address.

**No public internet exposure.** The phone has no static IP and no port forwarding — the dashboard is reachable only from devices on the same local network.

## Step 1 — Find the Phone's LAN IP

On the Moto G51 in Termux:

```bash
# Method 1: ifconfig (most reliable)
ifconfig wlan0 | grep 'inet '
# Look for: inet 192.168.x.x

# Method 2: ip command
ip addr show wlan0 | grep 'inet '

# Method 3: Termux shortcut
termux-wifi-connectioninfo 2>/dev/null | grep ip
```

The IP is typically `192.168.1.x` or `192.168.0.x` on home Wi-Fi.

**Tip:** The bot prints its LAN IP at startup:
```
Dashboard: http://192.168.1.42:8000
```

## Step 2 — Start the Bot

```bash
cd ~/Ragi_bot
bash deploy/android/start_ragi.sh
```

The startup banner shows the exact URLs to use:

```
========================================================
  RAGI BOT — Self-Learning Options Trading Bot
========================================================
  Server:    0.0.0.0:8000
  Dashboard: http://192.168.1.42:8000
  Health:    http://192.168.1.42:8000/health
  Detailed:  http://192.168.1.42:8000/health/detailed
  Mode:      PAPER
========================================================
```

## Step 3 — Access from Laptop

Open a browser on any device connected to the same network and navigate to:

```
http://<PHONE_IP>:8000
```

For example: `http://192.168.1.42:8000`

- **Login page:** `http://192.168.1.42:8000/`
- **Dashboard:** `http://192.168.1.42:8000/dashboard` (after login)
- **Health check:** `http://192.168.1.42:8000/health`
- **Detailed health:** `http://192.168.1.42:8000/health/detailed`

## Step 4 — Verify Connectivity

From the laptop terminal or browser:

```bash
# Quick health check
curl http://192.168.1.42:8000/health

# Detailed status (includes DB, LLM, scheduler, trading mode)
curl http://192.168.1.42:8000/health/detailed | python3 -m json.tool
```

Expected response from `/health`:
```json
{"status": "ok", "service": "ragi-bot"}
```

## Health Endpoint Fields

The `/health/detailed` endpoint returns:

| Field | Description |
|-------|-------------|
| `status` | `ok` or `degraded` |
| `trading_mode` | `paper` or `live` |
| `bot_paused` | Whether the operator has paused trading |
| `feed_status` | `live` = receiving market data, `error` = data feed problem |
| `ai_status` | Current AI state: `waiting`, `analyzing`, `in_trade`, `paused` |
| `db` | `ok` or error message |
| `llm_provider` | Active AI provider name |
| `llm_available` | Whether the AI provider is reachable |
| `scheduler` | `running` or `unknown` |
| `positions_open` | Number of open trading positions |
| `last_tick` | Timestamp of last market analysis cycle |
| `realized_pnl` | Today's realized profit/loss |
| `cumulative_pnl` | All-time realized profit/loss |

## Configuring the Port

Default port is `8000`. Change it in `.env`:

```bash
APP_PORT=9000
```

Then access at `http://<PHONE_IP>:9000`.

## Troubleshooting

### Laptop cannot connect

1. **Same network?** Both phone and laptop must be on the same Wi-Fi / LAN.
2. **Bot running?** On the phone: `bash deploy/android/status_ragi.sh`
3. **Correct IP?** Phone IPs change when reconnecting to Wi-Fi. Re-check with `ifconfig wlan0`.
4. **Port blocked?** Some routers block inter-device traffic ("AP isolation" or "client isolation"). Check router settings.
5. **Firewall on laptop?** Unlikely for outbound HTTP, but check if a VPN or firewall blocks local network access.

```bash
# From laptop, test raw connectivity
ping 192.168.1.42
curl -v http://192.168.1.42:8000/health
```

### IP keeps changing

If the phone gets a different IP each time it connects to Wi-Fi:
- Assign a **static IP** in Android Wi-Fi settings (Settings > Wi-Fi > your network > Advanced > IP settings > Static)
- Or assign a **DHCP reservation** in your router admin panel

### Connection drops

Mobile Wi-Fi can be unreliable. The bot continues running even if Wi-Fi drops — you just lose LAN monitoring until Wi-Fi reconnects. The bot uses mobile data for broker/market APIs independently.

### Dashboard loads but SSE stream doesn't update

The SSE (Server-Sent Events) stream requires authentication. Log in first at the root URL, then navigate to `/dashboard`.

## Network / Firewall Settings

**No special configuration needed** in most cases. The defaults work on standard home networks.

| Setting | Required Value |
|---------|---------------|
| Phone and laptop | Same Wi-Fi / LAN |
| Router AP isolation | Disabled (usually the default) |
| Phone firewall | None needed (Termux has no firewall) |
| Port forwarding | NOT needed (LAN only) |
| Static IP | Optional but recommended |

**Do NOT set up port forwarding** on your router. The dashboard is intended for local network access only and is not hardened for public internet exposure.

## Security Notes

- The dashboard requires login credentials (`BOT_USERNAME` / `BOT_PASSWORD` from `.env`)
- Brute-force protection limits failed login attempts
- All traffic is unencrypted HTTP on the local network — acceptable for LAN, not for public exposure
- The bot never initiates inbound connections; all broker/API communication is outbound HTTPS
