# tests/test_backtest_reporter.py
import pytest
from datetime import datetime, timedelta
from core.models import TradeRecord
from backtest.reporter import BacktestReporter


def _trade(pnl: float, entry_price: float = 60000.0, qty: float = 0.1) -> TradeRecord:
    now = datetime.utcnow()
    return TradeRecord(
        symbol="BTC/USDT", side="SELL",
        entry_price=entry_price,
        exit_price=entry_price + pnl / qty,
        quantity=qty,
        realized_pnl=pnl,
        entry_time=now,
        exit_time=now + timedelta(hours=2),
        exit_reason="TP" if pnl > 0 else "SL",
    )


def test_win_rate_all_winners():
    trades = [_trade(100), _trade(50), _trade(200)]
    report = BacktestReporter(trades).compute()
    assert report["win_rate"] == pytest.approx(1.0)


def test_win_rate_mixed():
    trades = [_trade(100), _trade(-50), _trade(200), _trade(-30)]
    report = BacktestReporter(trades).compute()
    assert report["win_rate"] == pytest.approx(0.5)


def test_total_pnl():
    trades = [_trade(100), _trade(-30), _trade(80)]
    report = BacktestReporter(trades).compute()
    assert report["total_pnl"] == pytest.approx(150.0)


def test_max_drawdown_is_negative_or_zero():
    trades = [_trade(100), _trade(-200), _trade(50)]
    report = BacktestReporter(trades).compute()
    assert report["max_drawdown"] <= 0


def test_max_drawdown_all_winners_is_zero():
    trades = [_trade(100), _trade(50)]
    report = BacktestReporter(trades).compute()
    assert report["max_drawdown"] == pytest.approx(0.0)


def test_sharpe_ratio_positive_for_consistent_winners():
    trades = [_trade(float(50 + i)) for i in range(20)]
    report = BacktestReporter(trades).compute()
    assert report["sharpe_ratio"] > 0


def test_empty_trades_returns_zeros():
    report = BacktestReporter([]).compute()
    assert report["total_pnl"] == 0.0
    assert report["win_rate"] == 0.0
    assert report["max_drawdown"] == 0.0
    assert report["sharpe_ratio"] == 0.0


def test_csv_export_creates_file(tmp_path):
    trades = [_trade(100), _trade(-50)]
    reporter = BacktestReporter(trades)
    path = tmp_path / "result.csv"
    reporter.export_csv(str(path))
    assert path.exists()
    lines = path.read_text().splitlines()
    assert len(lines) == 3  # header + 2 rows
    assert "realized_pnl" in lines[0]
