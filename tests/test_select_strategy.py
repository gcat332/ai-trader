from analysis.select_strategy import rank_results, slice_last_days


def test_rank_results_filters_by_trade_count_and_drawdown_then_sorts():
    rows = [
        {
            "strategy": "a",
            "sharpe_ratio": 2.0,
            "max_drawdown": 0.05,
            "total_trades": 40,
            "total_pnl": 100,
        },
        {
            "strategy": "b",
            "sharpe_ratio": 3.0,
            "max_drawdown": 0.20,
            "total_trades": 40,
            "total_pnl": 300,
        },
        {
            "strategy": "c",
            "sharpe_ratio": 2.5,
            "max_drawdown": 0.04,
            "total_trades": 10,
            "total_pnl": 50,
        },
        {
            "strategy": "d",
            "sharpe_ratio": 2.2,
            "max_drawdown": 0.06,
            "total_trades": 35,
            "total_pnl": 120,
        },
    ]

    ranked = rank_results(rows, min_trades=30, max_dd=0.10)

    assert [row["strategy"] for row in ranked] == ["d", "a"]


def test_slice_last_days_keeps_rows_at_or_after_cutoff():
    day_ms = 86_400_000
    candles = [
        [1_000, 1, 1, 1, 1, 1],
        [1_000 + day_ms, 1, 1, 1, 1, 1],
        [1_000 + 2 * day_ms, 1, 1, 1, 1, 1],
        [1_000 + 3 * day_ms, 1, 1, 1, 1, 1],
    ]

    sliced = slice_last_days(candles, 2)

    assert sliced == candles[1:]
