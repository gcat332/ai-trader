# Deploy: long-term paper test on Oracle Cloud Always Free

Run the bot 24/7 in **paper mode** on an Oracle Cloud **Always Free** VM to
collect results over weeks. Single light Python process — hourly tick +
occasional LogisticRegression retrain (≤500 rows) fits in 1 GB RAM.

> Why Oracle over GCP: Always Free **includes a public IPv4 at no cost** and
> 10 TB/mo egress, so an internet-connected 24/7 VM is genuinely $0. GCP now
> bills ~$3–4/mo for the external IPv4 even on its free e2-micro.

## 0. Account note

Always Free resources never expire, but Oracle **reclaims compute instances that
sit idle for 7 days** on free accounts. A bot under systemd with constant
network/CPU activity is not idle, so it's safe — just don't stop the service for
a week.

## 1. Create the VM

Oracle Cloud Console → **Compute → Instances → Create instance**:

- **Image:** Canonical **Ubuntu 24.04** (ships Python 3.12 — no extra setup)
- **Shape:** **VM.Standard.E2.1.Micro** (AMD, 1 OCPU / 1 GB) — Always Free, x86,
  always available. Enough here.
  - Optional: `VM.Standard.A1.Flex` (ARM) gives up to 4 OCPU / 24 GB free for
    huge headroom, but capacity is often *"out of host capacity"*. All deps have
    `aarch64` wheels, so it works if you can grab a slot.
- **Networking:** keep the default VCN. It already allows inbound SSH (22). We
  reach the dashboard via SSH tunnel, so **add no other ingress rules**.
- **SSH keys:** upload your public key (or let it generate one).

Note the instance's **public IP** when it's running.

## 2. First login + swap (OOM insurance)

```bash
ssh ubuntu@<public-ip>

sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h   # confirm 2 GB swap
```

## 3. Install the app

Ubuntu 24.04 already has Python 3.12.

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip git
git clone <your-repo-url> ai-trader && cd ai-trader

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install .
```

## 4. Configure `.env`

```bash
cat > .env <<'EOF'
PAPER_TRADING=true
BINANCE_TESTNET=true
BINANCE_TESTNET_API_KEY=...
BINANCE_TESTNET_API_SECRET=...

STRATEGY_MODE=multi
ARBITER_MODE=rule          # 'claude' costs Anthropic tokens per drift tick

# Prod cadence — representative results (NOT the 1m accel used for smoke tests)
TRADING_TIMEFRAME=1h
# LOOP_INTERVAL_SECONDS unset -> defaults to 3600

# Optional alerts
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

API_HOST=127.0.0.1         # localhost only; reach the dashboard via SSH tunnel
LOG_LEVEL=INFO
EOF
chmod 600 .env
```

> If you ever set `API_HOST=0.0.0.0` for remote access, you **must** also set
> `API_KEY` **and** open the port in the VCN security list — otherwise the
> start/stop/close control endpoints are open to anyone. Prefer the SSH tunnel.

## 5. systemd service (auto-restart)

The trading loop self-heals transient errors, but if the process itself dies it
needs a supervisor. `Restart=always` covers crashes and reboots.

```bash
sudo tee /etc/systemd/system/ai-trader.service <<EOF
[Unit]
Description=AI Trader (paper)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$HOME/ai-trader
ExecStart=$HOME/ai-trader/.venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now ai-trader
```

## 6. Verify

```bash
systemctl status ai-trader --no-pager
journalctl -u ai-trader -f                      # service stdout/stderr
tail -f ~/ai-trader/logs/trading.log            # structured JSON app log
```

Healthy start logs `Starting in PAPER TRADING mode` and (if configured)
`Telegram bot started`, with **no** repeating `Engine loop error` lines.

## 7. View the dashboard (from your laptop)

```bash
ssh -L 8000:localhost:8000 ubuntu@<public-ip>
# then open http://localhost:8000/api/pnl  (or run the React dashboard locally
# pointed at this API). Do NOT build/serve React on the VM — keep its 1 GB free.
```

## 8. Collect results + back up

Everything persists in `db/trades.db`. Pull it down periodically:

```bash
scp ubuntu@<public-ip>:~/ai-trader/db/trades.db ./trades-$(date +%F).db
```

Key endpoints / pages for the long-term test:
`/api/pnl`, `/api/decisions/metrics`, `/api/strategy-switches`,
`/api/compare` (real vs backtest equity, Sharpe, drawdown, win rate).

## Test plan recap

- **Duration:** ≥ 2–4 weeks. Hourly candles + `MIN_REGIME_SAMPLES=20`, arbiter
  1-day swap cooldown, and drift/AB needing 30–50 closed trades all mean
  meaningful signal takes weeks, not days.
- **Pass bar before real money:** stable uptime, no naked positions (OCO works),
  risk-adjusted return ≥ backtest on the Compare page, drift detector behaving,
  no unhandled crashes in `journalctl`.
