from types import SimpleNamespace
from unittest.mock import MagicMock

import main
from main import _build_paper_exchange_for


def test_futures_loop_gets_paper_futures_exchange():
    cfg = SimpleNamespace(market="futures", leverage=3)

    ex = _build_paper_exchange_for(cfg, initial_balance={"USDT": 10000.0})

    assert ex.__class__.__name__ == "PaperFuturesExchange"


def test_spot_loop_gets_paper_exchange():
    cfg = SimpleNamespace(market="spot", leverage=1)

    ex = _build_paper_exchange_for(cfg, initial_balance={"USDT": 10000.0})

    assert ex.__class__.__name__ == "PaperExchange"


def test_live_futures_loop_builds_binance_futures_exchange(monkeypatch):
    factory = getattr(main, "_build_live_exchange_for", None)
    assert factory is not None
    spot_exchange = object()
    futures_exchange = object()
    futures_cls = MagicMock(return_value=futures_exchange)
    monkeypatch.setattr(main, "BinanceFuturesExchange", futures_cls)
    cfg = SimpleNamespace(market="futures", leverage=7)
    settings = SimpleNamespace(
        binance_api_key="key",
        binance_api_secret="secret",
        binance_testnet=True,
    )

    ex = factory(cfg, settings, spot_exchange)

    assert ex is futures_exchange
    futures_cls.assert_called_once_with(
        api_key="key",
        api_secret="secret",
        testnet=True,
        leverage=7,
    )


def test_live_spot_loop_reuses_spot_exchange():
    factory = getattr(main, "_build_live_exchange_for", None)
    assert factory is not None
    spot_exchange = object()
    cfg = SimpleNamespace(market="spot", leverage=1)
    settings = SimpleNamespace(
        binance_api_key="key",
        binance_api_secret="secret",
        binance_testnet=True,
    )

    ex = factory(cfg, settings, spot_exchange)

    assert ex is spot_exchange
