"""Futures strategy selection using the paper futures replay path."""
from __future__ import annotations

import asyncio

from analysis.select_strategy import rank_results, slice_last_days


async def run_single_strategy_futures(
    name,
    candles,
    *,
    leverage=3,
    initial_balance=1000.0,
) -> dict:
    from analysis.run_backtests import make_strategy
    from backtest.reporter import BacktestReporter
    from core.engine import Engine
    from exchange.paper_futures import PaperFuturesExchange
    from risk.manager import RiskManager

    try:
        from analysis.run_backtests import SYMBOL
    except ImportError:
        SYMBOL = "BTC/USDT"

    exchange = PaperFuturesExchange({"USDT": initial_balance}, leverage=leverage)
    engine = Engine(
        exchange=exchange,
        strategy=make_strategy(name),
        symbol=SYMBOL,
        timeframe="1h",
        risk_manager=RiskManager(),
        market="futures",
        leverage=leverage,
    )
    for i, candle in enumerate(candles):
        window = candles[max(0, i - 249): i + 1]
        await engine.process_candles(window)
        _, high, low, close = candle[1], candle[2], candle[3], candle[4]
        exchange.tick(SYMBOL, high=high, low=low, close=close)

    if hasattr(exchange, "get_trade_log"):
        trades = exchange.get_trade_log()
    else:
        trades = exchange.closed_trades
    metrics = BacktestReporter(trades).compute()
    short_trades = sum(1 for t in trades if t.side == "BUY")
    long_trades = sum(1 for t in trades if t.side == "SELL")

    return {
        "strategy": name,
        "total_trades": metrics["total_trades"],
        "short_trades": short_trades,
        "long_trades": long_trades,
        "total_pnl": metrics["total_pnl"],
        "sharpe_ratio": metrics["sharpe_ratio"],
        "max_drawdown": metrics["max_drawdown"],
    }


def select_strategy_futures(
    candles_by_tf,
    *,
    leverage=3,
    min_trades=15,
    max_dd=0.10,
) -> dict:
    candidates = ("supertrend",)
    rows = []
    for tf, candles in candles_by_tf.items():
        for name in candidates:
            result = asyncio.run(
                run_single_strategy_futures(name, candles, leverage=leverage)
            )
            result["timeframe"] = tf
            rows.append(result)

    ranked = rank_results(rows, min_trades=min_trades, max_dd=max_dd)
    return {
        "ranked": ranked,
        "supertrend_short_validated": any(
            r["strategy"] == "supertrend" and r["short_trades"] > 0 for r in ranked
        ),
    }
