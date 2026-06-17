"""Run the project's real BacktestRunner/Engine/RiskManager/strategies against
cached BTC/USDT history across multiple timeframes, plus a faithful offline
replay of the production regime-switching MetaStrategy + StrategyArbiter.

Read-only analysis script: imports the app's actual strategy/risk/backtest
code unmodified so results reflect production logic exactly.
"""
import asyncio
import csv
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from backtest.runner import BacktestRunner  # noqa: E402
from backtest.reporter import BacktestReporter  # noqa: E402
from risk.manager import RiskManager  # noqa: E402
from strategy.ml.dummy_model import DummyModel  # noqa: E402
from strategy.rsi_macd import RsiMacdStrategy  # noqa: E402
from strategy.bollinger_reversion import BollingerReversionStrategy  # noqa: E402
from strategy.ema_cross import EmaCrossStrategy  # noqa: E402
from strategy.trend_pullback import TrendPullbackStrategy  # noqa: E402
from strategy.liquidation_reversion import LiquidationReversionStrategy  # noqa: E402
from strategy.regime import RegimeClassifier  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUT_PATH = os.path.join(os.path.dirname(__file__), "results.json")

TIMEFRAMES_PER_YEAR = {
    "30m": 365 * 48,
    "1h": 365 * 24,
    "4h": 365 * 6,
    "1d": 365,
}

INITIAL_BALANCE = {"USDT": 10000.0}
SYMBOL = "BTC/USDT"


def load_candles(timeframe: str) -> list[list]:
    path = os.path.join(DATA_DIR, f"BTCUSDT_{timeframe}.csv")
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append([
                int(r["timestamp"]), float(r["open"]), float(r["high"]),
                float(r["low"]), float(r["close"]), float(r["volume"]),
            ])
    return rows


def make_strategy(name: str):
    model = DummyModel(confidence=0.75)
    if name == "rsi_macd":
        return RsiMacdStrategy(ml_model=model)
    if name == "bollinger_reversion":
        return BollingerReversionStrategy(ml_model=model)
    if name == "ema_cross":
        return EmaCrossStrategy(ml_model=model)
    if name == "trend_pullback":
        return TrendPullbackStrategy(ml_model=model)
    if name == "liquidation_reversion":
        return LiquidationReversionStrategy(ml_model=model)
    raise ValueError(name)


STRATEGY_NAMES = [
    "rsi_macd", "bollinger_reversion", "ema_cross",
    "trend_pullback", "liquidation_reversion",
]


def sharpe_from_trades(trades, periods_per_year: int) -> float:
    if len(trades) < 2:
        return 0.0
    pnls = [t.realized_pnl for t in trades]
    mean = sum(pnls) / len(pnls)
    variance = sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1)
    std = math.sqrt(variance)
    if std == 0:
        return 0.0
    # Annualize by actual average holding time, not a fixed per-timeframe guess --
    # more honest across strategies whose trade frequency differs.
    total_hours = sum(
        (t.exit_time - t.entry_time).total_seconds() / 3600 for t in trades
    )
    avg_hold_hours = total_hours / len(trades) if total_hours > 0 else 1.0
    trades_per_year = (365 * 24) / avg_hold_hours if avg_hold_hours > 0 else periods_per_year
    return (mean / std) * math.sqrt(max(trades_per_year, 1.0))


async def run_single_strategy(name: str, candles: list[list]) -> dict:
    strategy = make_strategy(name)
    risk_manager = RiskManager()
    runner = BacktestRunner(
        strategy=strategy, risk_manager=risk_manager,
        initial_balance=INITIAL_BALANCE, symbol=SYMBOL,
    )
    trades = await runner.run(candles)
    reporter = BacktestReporter(trades)
    metrics = reporter.compute()
    metrics["sharpe_ratio_by_hold_time"] = sharpe_from_trades(trades, 0)
    metrics["strategy"] = name
    return metrics


async def run_multi_mode(candles: list[list], timeframe: str) -> dict:
    """Faithful offline replay of STRATEGY_MODE=multi: MetaStrategy dispatch +
    the production rule-based StrategyArbiter (core/strategy_arbiter.py),
    using the same regime classification and decision thresholds as
    core/trading_loop.py (DEFAULT_STRATEGY=rsi_macd default, drift check
    cadence approximated as 'on every closed trade' since this offline replay
    has no drift-detector wired and the arbiter's own logic is what's under
    test, not the drift trigger)."""
    from core.strategy_arbiter import StrategyArbiter
    from core.engine import Engine
    from exchange.paper import PaperExchange
    from datetime import datetime, timedelta, timezone

    strategies = {name: make_strategy(name) for name in STRATEGY_NAMES}
    active = "rsi_macd"
    arbiter = StrategyArbiter(
        strategies=STRATEGY_NAMES, swap_margin=0.10,
        min_regime_samples=20, epsilon=0.10, rng=random.Random(42),
    )
    regime_classifier = RegimeClassifier()
    risk_manager = RiskManager()
    exchange = PaperExchange(initial_balance=dict(INITIAL_BALANCE))

    # Per-(strategy, regime) running stats, fed by trades as they close --
    # mirrors what core/strategy_arbiter.py reads from repo.get_strategy_profiles().
    profiles: dict[tuple[str, str], dict] = {}

    def profile_list() -> list[dict]:
        return [
            {"strategy_id": s, "regime": r, "win_rate": p["wins"] / p["n"] if p["n"] else 0.0,
             "sample_count": p["n"]}
            for (s, r), p in profiles.items()
        ]

    all_trades = []
    last_switch_time = None
    swap_cooldown = timedelta(days=1)
    drift_check_every = 10
    tick = 0

    for i, candle in enumerate(candles):
        window = candles[max(0, i - 249): i + 1]  # 250 candles: warms up EMA200 (trend_pullback)
        df = pd.DataFrame(window, columns=["timestamp", "open", "high", "low", "close", "volume"])
        regime = regime_classifier.classify(df)

        engine = Engine(
            exchange=exchange, strategy=strategies[active], symbol=SYMBOL,
            timeframe=timeframe, risk_manager=risk_manager,
        )
        await engine.process_candles(window)

        _, high, low, close = candle[1], candle[2], candle[3], candle[4]
        fills = await exchange.tick(SYMBOL, high=high, low=low, close=close)
        for trade in exchange.get_trade_log()[-len(fills):] if fills else []:
            trade.strategy_id = active
            all_trades.append(trade)
            key = (active, regime)
            p = profiles.setdefault(key, {"wins": 0, "n": 0})
            p["n"] += 1
            if trade.realized_pnl > 0:
                p["wins"] += 1

        tick += 1
        if tick % drift_check_every == 0:
            candle_time = datetime.fromtimestamp(candle[0] / 1000, tz=timezone.utc)
            cooldown_ok = (
                last_switch_time is None or (candle_time - last_switch_time) >= swap_cooldown
            )
            if cooldown_ok:
                decision = arbiter.decide(regime, active, profile_list())
                if decision.decision in ("SWAP", "EXPLORE") and decision.to_strategy != active:
                    active = decision.to_strategy
                    last_switch_time = candle_time

    reporter = BacktestReporter(all_trades)
    metrics = reporter.compute()
    metrics["sharpe_ratio_by_hold_time"] = sharpe_from_trades(all_trades, 0)
    metrics["strategy"] = "multi_mode (rule arbiter)"
    metrics["final_active_technique"] = active
    metrics["regime_profiles"] = {f"{s}/{r}": v for (s, r), v in profiles.items()}
    return metrics


async def main():
    results: dict[str, list[dict]] = {}
    for timeframe in TIMEFRAMES_PER_YEAR:
        path = os.path.join(DATA_DIR, f"BTCUSDT_{timeframe}.csv")
        if not os.path.exists(path):
            print(f"[skip] no data for {timeframe}")
            continue
        candles = load_candles(timeframe)
        print(f"\n=== {timeframe} ({len(candles)} candles) ===")
        tf_results = []
        for name in STRATEGY_NAMES:
            metrics = await run_single_strategy(name, candles)
            tf_results.append(metrics)
            print(f"  {name:24s} trades={metrics['total_trades']:5d} "
                  f"win_rate={metrics['win_rate']:.1%} "
                  f"pnl={metrics['total_pnl']:+.2f} "
                  f"sharpe={metrics['sharpe_ratio_by_hold_time']:.2f}")

        multi_metrics = await run_multi_mode(candles, timeframe)
        tf_results.append(multi_metrics)
        print(f"  {'multi_mode (rule arbiter)':24s} trades={multi_metrics['total_trades']:5d} "
              f"win_rate={multi_metrics['win_rate']:.1%} "
              f"pnl={multi_metrics['total_pnl']:+.2f} "
              f"sharpe={multi_metrics['sharpe_ratio_by_hold_time']:.2f} "
              f"final_active={multi_metrics['final_active_technique']}")

        results[timeframe] = tf_results

    with open(OUT_PATH, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nSaved -> {OUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
