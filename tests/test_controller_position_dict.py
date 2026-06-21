from core.live_controller import LiveEngineController
from core.models import Position


def _pos(**kw):
    base = dict(
        symbol="BTC/USDT", side="LONG", entry_price=60000.0, quantity=0.1,
        unrealized_pnl=12.5, take_profit=None, stop_loss=None, mode="FUTURES",
        leverage=5, liquidation_price=54000.0,
    )
    base.update(kw)
    return Position(**base)


def test_position_dict_exposes_futures_fields():
    d = LiveEngineController._position_dict(_pos())
    assert d["side"] == "LONG"
    assert d["mode"] == "FUTURES"
    assert d["leverage"] == 5
    assert d["liquidation_price"] == 54000.0
    assert d["entry_price"] == 60000.0
    # initial_margin = 60000 * 0.1 / 5 = 1200
    assert d["initial_margin"] == 1200.0
    # legacy keys preserved
    assert d["symbol"] == "BTC/USDT"
    assert d["quantity"] == 0.1
    assert d["unrealized_pnl"] == 12.5


def test_position_dict_spot_defaults():
    d = LiveEngineController._position_dict(
        _pos(mode="SPOT", leverage=1, liquidation_price=None)
    )
    assert d["mode"] == "SPOT"
    assert d["leverage"] == 1
    assert d["liquidation_price"] is None
    # initial_margin falls back to notional when leverage == 1
    assert d["initial_margin"] == 6000.0
