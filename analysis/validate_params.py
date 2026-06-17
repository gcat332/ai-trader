"""Does the real trained ML model help or just choke the best rsi_macd config?
Compares the best-fit 1h gatekeeper (long_only + EMA200 + rsi 50/50) under:
  - DummyModel(0.75)  -> rules only (no gate), baseline +19.4
  - the real loaded model at several confidence_thresholds
so we can pick a threshold where the model filters without killing all trades."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.run_backtests import load_candles, INITIAL_BALANCE, SYMBOL  # noqa: E402
from backtest.runner import BacktestRunner  # noqa: E402
from backtest.reporter import BacktestReporter  # noqa: E402
from risk.manager import RiskManager  # noqa: E402
from strategy.ml.dummy_model import DummyModel  # noqa: E402
from strategy.rsi_macd import RsiMacdStrategy  # noqa: E402
from core.strategy_factory import load_ml_model  # noqa: E402

BEST = dict(rsi_oversold=50, rsi_overbought=50, adx_trend_threshold=20,
            atr_sl_mult=2.0, atr_tp_mult=3.0, long_only=True, trend_filter_period=200)


async def run(candles, label, model, conf):
    strat = RsiMacdStrategy(ml_model=model, confidence_threshold=conf, **BEST)
    runner = BacktestRunner(strategy=strat, risk_manager=RiskManager(),
                            initial_balance=INITIAL_BALANCE, symbol=SYMBOL)
    trades = await runner.run(candles)
    m = BacktestReporter(trades).compute()
    print(f"  {label:34s} trades={m['total_trades']:3d} wr={m['win_rate']:.1%} "
          f"pnl={m['total_pnl']:+.1f} dd={m['max_drawdown']:+.1f}", flush=True)


async def main():
    c = load_candles("1h")
    real = load_ml_model("models")
    print(f"1h candles: {len(c)}  real model: {type(real).__name__}\n", flush=True)
    await run(c, "DummyModel(0.75) rules-only", DummyModel(0.75), 0.6)
    for conf in [0.40, 0.45, 0.48, 0.50, 0.55]:
        await run(c, f"real model  thr={conf}", real, conf)


if __name__ == "__main__":
    asyncio.run(main())
