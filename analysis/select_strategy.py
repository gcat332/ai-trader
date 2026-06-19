"""Rank rule-based strategies on recent cached backtest data."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Iterable

from analysis.run_backtests import INITIAL_BALANCE, run_single_strategy

OUT_PATH = os.path.join(os.path.dirname(__file__), "strategy_selection.json")

RULE_STRATEGIES = [
    "rsi_macd",
    "bollinger_reversion",
    "ema_cross",
    "trend_pullback",
    "liquidation_reversion",
]

METRIC_KEYS = (
    "total_pnl",
    "win_rate",
    "max_drawdown",
    "sharpe_ratio",
    "total_trades",
    "avg_pnl",
)


def _reporter_drawdown_fraction(max_drawdown: float) -> float:
    balance = float(INITIAL_BALANCE["USDT"])
    return max_drawdown / balance


def rank_results(
    rows: Iterable[dict], *, min_trades: int = 30, max_dd: float = 0.10
) -> list[dict]:
    kept = [
        row
        for row in rows
        if row["total_trades"] >= min_trades and abs(row["max_drawdown"]) <= max_dd
    ]
    return sorted(
        kept,
        key=lambda row: (row["sharpe_ratio"], row["total_pnl"]),
        reverse=True,
    )


def slice_last_days(candles: list[list], days: int) -> list[list]:
    if not candles:
        return []
    max_ts = max(row[0] for row in candles)
    cutoff = max_ts - days * 86_400_000
    return [row for row in candles if row[0] >= cutoff]


def select_strategy(
    candles_by_tf: dict[str, list[list]],
    strategies: Iterable[str],
    *,
    min_trades: int = 30,
    max_dd: float = 0.10,
) -> list[dict]:
    rows = []
    for timeframe, candles in candles_by_tf.items():
        for name in strategies:
            metrics = asyncio.run(run_single_strategy(name, candles))
            selected_metrics = {key: metrics.get(key, 0.0) for key in METRIC_KEYS}
            selected_metrics["max_drawdown"] = _reporter_drawdown_fraction(
                selected_metrics["max_drawdown"]
            )
            rows.append({
                "strategy": name,
                "timeframe": timeframe,
                **selected_metrics,
            })

    ranked = rank_results(rows, min_trades=min_trades, max_dd=max_dd)
    with open(OUT_PATH, "w") as f:
        json.dump(ranked, f, indent=2)
    return ranked


def _print_ranked_table(ranked: list[dict]) -> None:
    columns = (
        "strategy",
        "timeframe",
        "sharpe_ratio",
        "max_drawdown",
        "total_trades",
        "total_pnl",
    )
    print(" | ".join(columns))
    print(" | ".join("-" * len(column) for column in columns))
    for row in ranked:
        print(
            f"{row['strategy']} | "
            f"{row['timeframe']} | "
            f"{row['sharpe_ratio']:.4f} | "
            f"{row['max_drawdown']:.4f} | "
            f"{row['total_trades']} | "
            f"{row['total_pnl']:.4f}"
        )


def main() -> None:
    from analysis.run_backtests import load_candles

    candles_by_tf = {
        "30m": load_candles("30m"),
        "1h": load_candles("1h"),
        "4h": load_candles("4h"),
    }
    candles_by_tf = {
        timeframe: slice_last_days(candles, 60)
        for timeframe, candles in candles_by_tf.items()
    }
    ranked = select_strategy(candles_by_tf, RULE_STRATEGIES, min_trades=15, max_dd=0.10)
    _print_ranked_table(ranked)
    top_strategy = ranked[0]["strategy"] if ranked else "None"
    print(f"Top-ranked strategy: {top_strategy}")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
