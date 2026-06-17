"""Fetch 2 years of BTC/USDT OHLCV from Binance MAINNET (public market data,
no API key needed) for multiple timeframes, cached to CSV for reuse."""
import csv
import os
import time

import ccxt

SYMBOL = "BTC/USDT"
TIMEFRAMES = ["30m", "1h", "4h", "1d"]
DAYS_BACK = 365 * 2
OUT_DIR = os.path.join(os.path.dirname(__file__), "data")


def fetch_all(exchange, symbol, timeframe, since_ms, until_ms):
    candles = []
    cursor = since_ms
    while cursor < until_ms:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=cursor, limit=1000)
        if not batch:
            break
        candles.extend(batch)
        last_ts = batch[-1][0]
        if last_ts <= cursor:
            break
        cursor = last_ts + 1
        if len(batch) < 1000:
            break
        time.sleep(exchange.rateLimit / 1000.0)
    return [c for c in candles if c[0] <= until_ms]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    exchange = ccxt.binance({"enableRateLimit": True,
                              "options": {"defaultType": "spot"}})
    now_ms = exchange.milliseconds()
    since_ms = now_ms - DAYS_BACK * 24 * 60 * 60 * 1000

    for tf in TIMEFRAMES:
        out_path = os.path.join(OUT_DIR, f"BTCUSDT_{tf}.csv")
        if os.path.exists(out_path):
            print(f"[skip] {out_path} already exists")
            continue
        print(f"Fetching {SYMBOL} {tf} from Binance mainnet ...")
        candles = fetch_all(exchange, SYMBOL, tf, since_ms, now_ms)
        with open(out_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
            writer.writerows(candles)
        print(f"  saved {len(candles)} candles -> {out_path}")


if __name__ == "__main__":
    main()
