import pytest

import analysis.select_strategy as select_strategy_module
from analysis.select_strategy import rank_results, select_strategy, slice_last_days


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


def test_rank_results_filters_negative_drawdown_by_magnitude():
    rows = [
        {
            "strategy": "acceptable",
            "sharpe_ratio": 2.0,
            "max_drawdown": -0.05,
            "total_trades": 40,
            "total_pnl": 100,
        },
        {
            "strategy": "too_deep",
            "sharpe_ratio": 3.0,
            "max_drawdown": -0.20,
            "total_trades": 40,
            "total_pnl": 300,
        },
    ]

    ranked = rank_results(rows, min_trades=30, max_dd=0.10)

    assert [row["strategy"] for row in ranked] == ["acceptable"]


def test_select_strategy_normalizes_reporter_drawdown_to_fraction(tmp_path, monkeypatch):
    async def fake_run_single_strategy(name, candles):
        return {
            "total_pnl": 10.0,
            "win_rate": 1.0,
            "max_drawdown": -20.0,
            "sharpe_ratio": 1.5,
            "total_trades": 20,
            "avg_pnl": 0.5,
        }

    monkeypatch.setattr(
        select_strategy_module,
        "run_single_strategy",
        fake_run_single_strategy,
    )
    monkeypatch.setattr(
        select_strategy_module,
        "OUT_PATH",
        str(tmp_path / "strategy_selection.json"),
    )

    ranked = select_strategy(
        {"30m": [[1, 1, 1, 1, 1, 1]]},
        ["ema_cross"],
        min_trades=15,
        max_dd=0.10,
    )

    assert len(ranked) == 1
    assert ranked[0]["strategy"] == "ema_cross"
    assert ranked[0]["max_drawdown"] == pytest.approx(-0.002)


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
