import asyncio

from analysis.select_strategy import rank_results as spot_rank_results
from analysis.select_strategy_futures import (
    rank_results as futures_rank_results,
    run_single_strategy_futures,
)


def _synthetic_flip_candles():
    candles = []
    ts = 1_700_000_000_000
    price = 50_000.0
    for i in range(30):
        candles.append((ts + i * 3_600_000, price, price + 50, price - 50, price + 20, 100.0))
        price += 200
    for i in range(50):
        candles.append(
            (ts + (30 + i) * 3_600_000, price, price + 50, price - 50, price - 30, 100.0)
        )
        price -= 300
    return candles


def test_rank_results_reused_unchanged():
    assert futures_rank_results is spot_rank_results


def test_futures_selection_routes_sell_signals_as_shorts():
    result = asyncio.run(
        run_single_strategy_futures("supertrend", _synthetic_flip_candles(), leverage=3)
    )

    assert result["total_trades"] > 0, "Expected trades but got 0. Check candle construction."
    assert (
        result["short_trades"] > 0
    ), f"Expected short trades but got {result['short_trades']}. SELL signals may not be routing to shorts."
