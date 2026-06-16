"""One-off: backtest all 5 strategies on the same BTC/USDT history and compare.

Uses a 250-candle rolling window (the stock BacktestRunner caps at 100, which
starves EMA200 strategies). Public mainnet OHLCV — no API keys needed.
Run: .venv/bin/python scripts/backtest_compare.py
"""
import asyncio
import csv
import io
import sys
import urllib.request
import zipfile

from core.engine import Engine
from exchange.paper import PaperExchange
from risk.manager import RiskManager
from backtest.reporter import BacktestReporter
from strategy.ml.dummy_model import DummyModel
from strategy.rsi_macd import RsiMacdStrategy
from strategy.bollinger_reversion import BollingerReversionStrategy
from strategy.ema_cross import EmaCrossStrategy
from strategy.trend_pullback import TrendPullbackStrategy
from strategy.liquidation_reversion import LiquidationReversionStrategy

SYMBOL = "BTC/USDT"
TIMEFRAME = sys.argv[1] if len(sys.argv) > 1 else "1d"  # e.g. 1d, 4h, 1h
WINDOW = 250
# Binance trading APIs are network-blocked here; data.binance.vision (public
# historical dumps) is reachable. Pull monthly klines and concatenate.
VISION = ("https://data.binance.vision/data/spot/monthly/klines/"
          f"BTCUSDT/{TIMEFRAME}/BTCUSDT-{TIMEFRAME}-{{m}}.zip")
MONTHS = [f"{y}-{mo:02d}" for y in range(2023, 2027) for mo in range(1, 13)
          if (y, mo) <= (2026, 5)]

BUILDERS = {
    "rsi_macd": lambda: RsiMacdStrategy(ml_model=DummyModel(0.75)),
    "bollinger_reversion": lambda: BollingerReversionStrategy(ml_model=DummyModel(0.75)),
    "ema_cross": lambda: EmaCrossStrategy(ml_model=DummyModel(0.75)),
    "trend_pullback": lambda: TrendPullbackStrategy(ml_model=DummyModel(0.75)),
    "liquidation_reversion": lambda: LiquidationReversionStrategy(ml_model=DummyModel(0.75)),
}


def fetch():
    """Download monthly 1d klines from data.binance.vision → [[ts,o,h,l,c,v], ...]."""
    candles = []
    for m in MONTHS:
        try:
            raw = urllib.request.urlopen(VISION.format(m=m), timeout=30).read()
        except Exception:
            continue  # month not published yet → skip
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            data = z.read(z.namelist()[0]).decode()
        for row in csv.reader(io.StringIO(data)):
            if not row or row[0].lower().startswith("open"):  # skip stray header
                continue
            ts = int(float(row[0]))
            if ts > 10**14:   # binance switched to microsecond timestamps in 2025+
                ts //= 1000
            candles.append([ts] + [float(x) for x in row[1:6]])
    candles.sort(key=lambda c: c[0])
    return candles


async def run_one(strategy, candles):
    exchange = PaperExchange(initial_balance={"USDT": 10000.0})
    engine = Engine(exchange=exchange, strategy=strategy, symbol=SYMBOL,
                    timeframe=TIMEFRAME, risk_manager=RiskManager())
    for i, candle in enumerate(candles):
        window = candles[max(0, i - (WINDOW - 1)): i + 1]
        await engine.process_candles(window)
        await exchange.tick(SYMBOL, high=candle[2], low=candle[3], close=candle[4])
    return exchange.get_trade_log()


async def main():
    candles = fetch()
    from datetime import datetime, timezone
    d0 = datetime.fromtimestamp(candles[0][0] / 1000, timezone.utc).date()
    d1 = datetime.fromtimestamp(candles[-1][0] / 1000, timezone.utc).date()
    print(f"{SYMBOL} {TIMEFRAME}  {len(candles)} candles  ({d0} .. {d1})\n")
    rows = []
    for name, build in BUILDERS.items():
        trades = await run_one(build(), candles)
        s = BacktestReporter(trades).compute()
        rows.append((name, s))

    hdr = f"{'strategy':<22}{'trades':>7}{'win%':>7}{'PnL':>12}{'maxDD':>11}{'Sharpe':>8}"
    print(hdr); print("-" * len(hdr))
    for name, s in rows:
        print(f"{name:<22}{s['total_trades']:>7}{s['win_rate']*100:>6.0f}%"
              f"{s['total_pnl']:>12.1f}{s['max_drawdown']:>11.1f}{s['sharpe_ratio']:>8.2f}")


if __name__ == "__main__":
    asyncio.run(main())
