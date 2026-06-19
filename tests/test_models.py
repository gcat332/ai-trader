from datetime import datetime
import pytest
from core.models import Signal, Order, Position


def test_signal_defaults():
    sig = Signal(
        symbol="BTC/USDT",
        side="BUY",
        entry_price=65000.0,
        take_profit=67000.0,
        stop_loss=63500.0,
        trailing_sl=False,
        confidence=0.85,
        strategy_id="rsi_ml_v1",
        timestamp=datetime(2026, 1, 1, 12, 0),
    )
    assert sig.symbol == "BTC/USDT"
    assert sig.side == "BUY"
    assert sig.confidence == 0.85


def test_signal_hold_has_no_prices():
    sig = Signal(
        symbol="ETH/USDT",
        side="HOLD",
        entry_price=0.0,
        take_profit=None,
        stop_loss=None,
        trailing_sl=False,
        confidence=0.3,
        strategy_id="rsi_ml_v1",
        timestamp=datetime(2026, 1, 1, 12, 0),
    )
    assert sig.take_profit is None
    assert sig.stop_loss is None


def test_order_status_default():
    order = Order(
        id="ord-001",
        symbol="BTC/USDT",
        side="BUY",
        type="LIMIT",
        quantity=0.01,
        price=65000.0,
        status="PENDING",
        exchange_order_id=None,
    )
    assert order.status == "PENDING"
    assert order.exchange_order_id is None


def test_position_pnl_field():
    pos = Position(
        symbol="BTC/USDT",
        side="LONG",
        entry_price=65000.0,
        quantity=0.01,
        unrealized_pnl=20.0,
        take_profit=67000.0,
        stop_loss=63500.0,
        mode="SPOT",
    )
    assert pos.unrealized_pnl == 20.0
    assert pos.mode == "SPOT"


from core.models import Order, Position

def test_order_reduce_only_defaults_false():
    o = Order(id="1", symbol="BTC/USDT", side="SELL", type="MARKET",
              quantity=1.0, price=None, status="PENDING", exchange_order_id=None)
    assert o.reduce_only is False

def test_position_futures_fields_default():
    p = Position(symbol="BTC/USDT", side="SHORT", entry_price=100.0, quantity=1.0,
                 unrealized_pnl=0.0, take_profit=None, stop_loss=None, mode="FUTURES")
    assert p.leverage == 1
    assert p.liquidation_price is None


from core.models import DecisionRecord, SignalOutcome, StrategyProfile, StrategySwitch


def test_decision_record_has_regime():
    from datetime import datetime
    from core.models import DecisionRecord
    rec = DecisionRecord(
        id="d1", timestamp=datetime(2026, 1, 1), symbol="BTC/USDT",
        strategy_id="rsi_macd", signal_side="BUY", confidence=0.8,
        narrative="x", final_decision="PLACED", rejection_reason=None,
        entry_price=65000.0, regime="TRENDING",
    )
    assert rec.regime == "TRENDING"


def test_strategy_profile_fields():
    p = StrategyProfile(strategy_id="rsi_macd", regime="SIDEWAYS",
                        win_rate=0.36, avg_pnl=-5.0, sample_count=42)
    assert p.regime == "SIDEWAYS"
    assert p.win_rate == 0.36


def test_strategy_switch_fields():
    from datetime import datetime
    sw = StrategySwitch(id="sw1", timestamp=datetime(2026, 1, 1), regime="SIDEWAYS",
                        from_strategy="rsi_macd", to_strategy="bollinger_reversion",
                        decision="SWAP", reason="rsi_macd weak in SIDEWAYS (36%) → bollinger (62%)")
    assert sw.decision == "SWAP"
    assert sw.to_strategy == "bollinger_reversion"


def test_signal_has_narrative_field():
    sig = Signal(
        symbol="BTC/USDT", side="BUY", entry_price=65000.0,
        take_profit=67000.0, stop_loss=63500.0, trailing_sl=False,
        confidence=0.88, strategy_id="rsi_macd", timestamp=datetime(2026, 1, 1),
    )
    # narrative defaults to empty string
    assert sig.narrative == ""


def test_signal_narrative_can_be_set():
    sig = Signal(
        symbol="BTC/USDT", side="BUY", entry_price=65000.0,
        take_profit=67000.0, stop_loss=63500.0, trailing_sl=False,
        confidence=0.88, strategy_id="rsi_macd", timestamp=datetime(2026, 1, 1),
        narrative="RSI=24.3 (oversold) | MACD bullish crossover → BUY",
    )
    assert "oversold" in sig.narrative


def test_decision_record_fields():
    from datetime import datetime
    rec = DecisionRecord(
        id="dec-001",
        timestamp=datetime(2026, 1, 1, 12, 0),
        symbol="BTC/USDT",
        strategy_id="rsi_macd",
        signal_side="BUY",
        confidence=0.88,
        narrative="RSI=24.3 (oversold) | MACD bullish crossover → BUY",
        final_decision="PLACED",
        rejection_reason=None,
        entry_price=65000.0,
    )
    assert rec.final_decision == "PLACED"
    assert rec.rejection_reason is None


def test_signal_outcome_fields():
    from core.models import SignalOutcome
    outcome = SignalOutcome(
        decision_id="dec-001",
        predicted_confidence=0.88,
        actual_outcome="WIN",
        realized_pnl=182.5,
        hold_duration_hours=3.5,
        exit_reason="TP",
    )
    assert outcome.actual_outcome == "WIN"
    assert outcome.realized_pnl == pytest.approx(182.5)
