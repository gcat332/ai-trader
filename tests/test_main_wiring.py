from types import SimpleNamespace

from main import _build_paper_exchange_for


def test_futures_loop_gets_paper_futures_exchange():
    cfg = SimpleNamespace(market="futures", leverage=3)

    ex = _build_paper_exchange_for(cfg, initial_balance={"USDT": 10000.0})

    assert ex.__class__.__name__ == "PaperFuturesExchange"


def test_spot_loop_gets_paper_exchange():
    cfg = SimpleNamespace(market="spot", leverage=1)

    ex = _build_paper_exchange_for(cfg, initial_balance={"USDT": 10000.0})

    assert ex.__class__.__name__ == "PaperExchange"
