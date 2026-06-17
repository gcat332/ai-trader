"""Tune ATR TP/SL for the Plan-C pair (ema_cross 1h + rsi_macd-default 4h),
real engine. Baseline atr 2/3 gives ema_cross 1h +196, rsi_macd 4h +67."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.run_backtests import load_candles, INITIAL_BALANCE, SYMBOL  # noqa: E402
from backtest.runner import BacktestRunner  # noqa: E402
from backtest.reporter import BacktestReporter  # noqa: E402
from risk.manager import RiskManager  # noqa: E402
from strategy.ml.dummy_model import DummyModel  # noqa: E402
from strategy.ema_cross import EmaCrossStrategy  # noqa: E402
from strategy.rsi_macd import RsiMacdStrategy  # noqa: E402

ATRS = [(2.0, 3.0), (1.5, 3.0), (2.0, 4.0), (1.5, 4.0), (2.5, 4.0), (3.0, 3.0), (1.5, 2.5)]


async def run(strat, candles):
    r = BacktestRunner(strategy=strat, risk_manager=RiskManager(),
                       initial_balance=INITIAL_BALANCE, symbol=SYMBOL)
    return BacktestReporter(await r.run(candles)).compute()


async def main():
    c1 = load_candles("1h")
    c4 = load_candles("4h")
    print("=== ema_cross 1h (vary ATR TP/SL) ===", flush=True)
    for sl, tp in ATRS:
        s = EmaCrossStrategy(ml_model=DummyModel(0.75), atr_sl_mult=sl, atr_tp_mult=tp)
        m = await run(s, c1)
        print(f"  atr {sl}/{tp}  trades={m['total_trades']:4d} wr={m['win_rate']:5.1%} "
              f"pnl={m['total_pnl']:+8.1f} dd={m['max_drawdown']:+7.1f} sharpe={m['sharpe_ratio']:5.1f}", flush=True)

    print("\n=== rsi_macd-default 4h (vary ATR TP/SL) ===", flush=True)
    for sl, tp in ATRS:
        s = RsiMacdStrategy(ml_model=DummyModel(0.75), atr_sl_mult=sl, atr_tp_mult=tp)
        m = await run(s, c4)
        print(f"  atr {sl}/{tp}  trades={m['total_trades']:4d} wr={m['win_rate']:5.1%} "
              f"pnl={m['total_pnl']:+8.1f} dd={m['max_drawdown']:+7.1f} sharpe={m['sharpe_ratio']:5.1f}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
