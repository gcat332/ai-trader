# backtest/reporter.py
import csv
import math
from core.models import TradeRecord


class BacktestReporter:

    def __init__(self, trades: list[TradeRecord]):
        self._trades = trades

    def compute(self) -> dict:
        if not self._trades:
            return {"total_pnl": 0.0, "win_rate": 0.0, "max_drawdown": 0.0,
                    "sharpe_ratio": 0.0, "total_trades": 0}

        pnls = [t.realized_pnl for t in self._trades]
        total_pnl = sum(pnls)
        win_rate = sum(1 for p in pnls if p > 0) / len(pnls)
        max_drawdown = self._calc_max_drawdown(pnls)
        sharpe = self._calc_sharpe(pnls)

        return {
            "total_pnl": total_pnl,
            "win_rate": win_rate,
            "max_drawdown": max_drawdown,
            "sharpe_ratio": sharpe,
            "total_trades": len(self._trades),
            "avg_pnl": total_pnl / len(self._trades),
        }

    def export_csv(self, path: str) -> None:
        fieldnames = [
            "symbol", "side", "entry_price", "exit_price", "quantity",
            "realized_pnl", "entry_time", "exit_time", "exit_reason",
        ]
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for t in self._trades:
                writer.writerow({
                    "symbol": t.symbol,
                    "side": t.side,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "quantity": t.quantity,
                    "realized_pnl": t.realized_pnl,
                    "entry_time": t.entry_time.isoformat(),
                    "exit_time": t.exit_time.isoformat(),
                    "exit_reason": t.exit_reason,
                })

    @staticmethod
    def _calc_max_drawdown(pnls: list[float]) -> float:
        """Compute the maximum drawdown from the per-trade PnL series.

        v1 modeling assumptions:
        - ``peak`` is initialised to 0 (i.e., initial capital baseline), so any
          cumulative loss from the very first trade counts as drawdown even if
          there was never a positive peak.
        - Returns a non-positive float; 0.0 means no drawdown occurred.
        """
        peak = 0.0
        cumulative = 0.0
        max_dd = 0.0
        for pnl in pnls:
            cumulative += pnl
            if cumulative > peak:
                peak = cumulative
            dd = cumulative - peak
            if dd < max_dd:
                max_dd = dd
        return max_dd

    @staticmethod
    def _calc_sharpe(pnls: list[float], periods_per_year: int = 365 * 24) -> float:
        """Compute an annualised Sharpe ratio from the per-trade PnL series.

        v1 modeling assumptions:
        - The return series is raw per-trade PnL in quote currency (e.g. USDT),
          not percentage returns. This makes the ratio scale-dependent on
          position size — it is useful for relative comparison between runs but
          not directly comparable to a conventional Sharpe computed on % returns.
        - Annualisation factor ``sqrt(365 * 24)`` assumes each trade corresponds
          to roughly one hourly period. For strategies with very different average
          holding times the factor should be adjusted accordingly.
        - Risk-free rate is assumed to be zero (typical for crypto backtests).
        """
        if len(pnls) < 2:
            return 0.0
        mean = sum(pnls) / len(pnls)
        variance = sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1)
        std = math.sqrt(variance)
        if std == 0:
            return 0.0
        return (mean / std) * math.sqrt(periods_per_year)
