# tests/test_contract_binance_futures_testnet.py
"""Contract / smoke test against the REAL Binance USDT-M FUTURES testnet.

OPT-IN: skipped unless RUN_CONTRACT_TESTS=1. Places real fake-money testnet futures
orders. Run before any futures go-live:
  RUN_CONTRACT_TESTS=1 .venv/bin/python -m pytest tests/test_contract_binance_futures_testnet.py -v
"""
import os
import uuid
import pytest
from dotenv import load_dotenv
from core.config import Settings
from core.models import Order

load_dotenv()

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_CONTRACT_TESTS") != "1",
    reason="contract tests hit Binance futures testnet (network + real testnet orders); set RUN_CONTRACT_TESTS=1",
)


@pytest.fixture
async def fx():
    from exchange.binance_futures import BinanceFuturesExchange
    s = Settings()
    ex = BinanceFuturesExchange(api_key=s.binance_api_key, api_secret=s.binance_api_secret,
                                testnet=s.binance_testnet, leverage=3)
    await ex._exchange.load_markets()
    yield ex
    await ex.close()


async def test_balance_and_funding(fx):
    bal = await fx.get_balance()
    assert "USDT" in bal
    rate = await fx.fetch_funding_rate("BTC/USDT")
    assert isinstance(rate, float)


async def test_open_protect_reports_liq_then_close(fx):
    sym = "BTC/USDT"
    px = float((await fx.fetch_ohlcv(sym, "1m", limit=1))[-1][4])
    qty = round(max(0.001, 30.0 / px), 3)  # clear futures min-notional (~5 USDT)

    opened = await fx.place_order(_buy(sym, qty), current_price=px)
    assert opened.status in ("FILLED", "OPEN")

    prot = await fx.protect_position(sym, side="BUY", quantity=qty,
                                     take_profit=round(px * 1.05, 1), stop_loss=round(px * 0.97, 1),
                                     current_price=px)
    assert prot is not None and prot.exchange_order_id

    positions = await fx.get_positions()
    pos = next(p for p in positions if p.symbol == sym)
    assert pos.liquidation_price is not None and pos.liquidation_price > 0  # exchange truth

    # Close reduce-only back to flat + cancel the resting protective leg.
    await fx.place_order(_sell(sym, qty, reduce_only=True), current_price=px)
    await fx.cancel_order(prot.exchange_order_id, sym)


def _buy(sym, qty):
    return Order(id=str(uuid.uuid4()), symbol=sym, side="BUY", type="MARKET", quantity=qty,
                 price=None, status="PENDING", exchange_order_id=None)

def _sell(sym, qty, reduce_only=False):
    return Order(id=str(uuid.uuid4()), symbol=sym, side="SELL", type="MARKET", quantity=qty,
                 price=None, status="PENDING", exchange_order_id=None, reduce_only=reduce_only)
