"""Compare every live strategy on 1h vs 4h with the REAL engine, so we can pick
a timeframe + strategy. rsi_macd uses the best-fit config (long_only + EMA200 +
50/50); others use their defaults. DummyModel(0.75) = rules only, no ML gate."""
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
from strategy.ema_cross import EmaCrossStrategy  # noqa: E402
from strategy.trend_pullback import TrendPullbackStrategy  # noqa: E402
from strategy.liquidation_reversion import LiquidationReversionStrategy  # noqa: E402

RSI_BEST = dict(rsi_oversold=50, rsi_overbought=50, adx_trend_threshold=20,
                atr_sl_mult=2.0, atr_tp_mult=3.0, long_only=True, trend_filter_period=200)


def make():
    d = DummyModel(0.75)
    return {
        "rsi_macd (best cfg)": RsiMacdStrategy(ml_model=d, **RSI_BEST),
        "rsi_macd (default)": RsiMacdStrategy(ml_model=d),
        "ema_cross": EmaCrossStrategy(ml_model=d),
        "trend_pullback": TrendPullbackStrategy(ml_model=d),
        "liquidation_reversion": LiquidationReversionStrategy(ml_model=d),
    }


async def run(strat, candles):
    r = BacktestRunner(strategy=strat, risk_manager=RiskManager(),
                       initial_balance=INITIAL_BALANCE, symbol=SYMBOL)
    return BacktestReporter(await r.run(candles)).compute()


async def main():
    for tf in ["1h", "4h"]:
        candles = load_candles(tf)
        print(f"\n=== {tf} ({len(candles)} candles, real engine) ===", flush=True)
        for name, strat in make().items():
            m = await run(strat, candles)
            print(f"  {name:24s} trades={m['total_trades']:4d} wr={m['win_rate']:5.1%} "
                  f"pnl={m['total_pnl']:+8.1f} dd={m['max_drawdown']:+7.1f} sharpe={m['sharpe_ratio']:6.1f}",
                  flush=True)


if __name__ == "__main__":
    asyncio.run(main())
