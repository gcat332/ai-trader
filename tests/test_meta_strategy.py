import pandas as pd
from datetime import datetime, timezone
from core.models import Signal
from strategy.base import BaseStrategy
from strategy.meta_strategy import MetaStrategy


class _Tagger(BaseStrategy):
    def __init__(self, sid): self._sid = sid
    @property
    def strategy_id(self): return self._sid
    def on_candle(self, symbol, ohlcv):
        return Signal(symbol=symbol, side="HOLD", entry_price=1.0, take_profit=None,
                      stop_loss=None, trailing_sl=False, confidence=0.0,
                      strategy_id=self._sid, timestamp=datetime.now(timezone.utc),
                      narrative=f"from {self._sid}")


def _ohlcv():
    return pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]})


def test_routes_to_active_strategy():
    meta = MetaStrategy({"a": _Tagger("a"), "b": _Tagger("b")}, active="a")
    sig = meta.on_candle("BTC/USDT", _ohlcv())
    assert sig.strategy_id == "a"


def test_switch_changes_active():
    meta = MetaStrategy({"a": _Tagger("a"), "b": _Tagger("b")}, active="a")
    meta.set_active("b")
    assert meta.active == "b"
    assert meta.on_candle("BTC/USDT", _ohlcv()).strategy_id == "b"


def test_active_ml_model_proxies_to_active_strategy():
    class _WithModel(_Tagger):
        def __init__(self, sid): super().__init__(sid); self._m = object()
        @property
        def ml_model(self): return self._m
        @ml_model.setter
        def ml_model(self, m): self._m = m
    meta = MetaStrategy({"a": _WithModel("a")}, active="a")
    new_model = object()
    meta.ml_model = new_model  # should proxy to active strategy
    assert meta.ml_model is new_model


def test_strategy_ids_lists_all():
    meta = MetaStrategy({"a": _Tagger("a"), "b": _Tagger("b")}, active="a")
    assert set(meta.strategy_ids) == {"a", "b"}
