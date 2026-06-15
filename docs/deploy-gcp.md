# Deploy: long-term paper test on GCP e2-micro

Run the bot 24/7 in **paper mode** on a Google Cloud e2-micro VM to collect
results over weeks. Single light Python process — hourly tick + occasional
LogisticRegression retrain (≤500 rows) fits in 1 GB RAM.

## Cost reality (read first)

- **Compute (e2-micro):** free under Always Free, *if* region + disk are correct (below).
- **External IPv4:** GCP bills ~$0.005/hr ≈ **$3–4/mo** — even on the free e2-micro.
  This is the one unavoidable charge for an internet-facing 24/7 VM.
- **The $300 / 90-day free trial credit covers everything, including the IP.** A
  2–4 week paper test runs at **$0 out of pocket** inside the trial window. After
  the trial, expect ~$3/mo for the IP.

To avoid surprise charges beyond the IP, the disk and region settings below are
not optional.

## 1. Create the VM

GCP Console → Compute Engine → Create instance:

- **Region:** `us-west1`, `us-central1`, or `us-east1` (only these qualify for the free e2-micro)
- **Machine type:** `e2-micro`
- **Boot disk:** Debian 12, **30 GB standard** persistent disk (SSD/balanced or >30 GB **bills**)
- **Firewall:** leave HTTP/HTTPS **off** — the dashboard is reached over SSH tunnel, not the public internet

Free-tier rule: exactly **one** e2-micro in a qualifying region.

## 2. First login + swap (OOM insurance)

```bash
gcloud compute ssh ai-trader   # or use the Console SSH button

sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h   # confirm 2 GB swap
```

## 3. Install Python 3.12 + the app

Debian 12 ships Python 3.11; the app needs ≥3.12.

```bash
sudo apt update && sudo apt install -y python3.12 python3.12-venv git
git clone <your-repo-url> ai-trader && cd ai-trader

python3.12 -m venv .venv
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
> `API_KEY` (and open the port) — otherwise the start/stop/close control
> endpoints are open to anyone. Prefer the SSH tunnel.

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
gcloud compute ssh ai-trader -- -L 8000:localhost:8000
# then open http://localhost:8000/api/pnl  (or run the React dashboard locally
# pointed at this API). Do NOT build/serve React on the VM — keep its 1 GB free.
```

## 8. Collect results + back up

Everything persists in `db/trades.db`. Pull it down periodically:

```bash
gcloud compute scp ai-trader:~/ai-trader/db/trades.db ./trades-$(date +%F).db
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
