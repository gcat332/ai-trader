# tests/test_contract_binance_testnet.py
"""Contract / smoke tests against the REAL Binance spot testnet.

These hit the network with real testnet API keys and place real (fake-money)
testnet orders, so they are OPT-IN: skipped unless RUN_CONTRACT_TESTS=1.

Why they exist: the OCO-protection bug (ccxt removed create_oco_order) and the
DataFetcher futures-testnet bug both passed 255 mocked unit tests while being
broken in production. Mocks can't catch "this exchange method no longer exists"
or "this client talks to the wrong base URL" — only a real call can. Run before
any go-live:  RUN_CONTRACT_TESTS=1 .venv/bin/python -m pytest tests/test_contract_binance_testnet.py -v
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
    reason="contract tests hit Binance testnet (network + real testnet orders); set RUN_CONTRACT_TESTS=1",
)


@pytest.fixture
async def exchange():
    from exchange.binance import BinanceExchange
    s = Settings()
    ex = BinanceExchange(
        api_key=s.binance_api_key,
        api_secret=s.binance_api_secret,
        testnet=s.binance_testnet,
    )
    await ex._exchange.load_markets()
    yield ex
    await ex.close()


async def test_get_balance_returns_usdt(exchange):
    bal = await exchange.get_balance()
    assert "USDT" in bal


async def test_fetch_ohlcv_returns_real_candles(exchange):
    candles = await exchange.fetch_ohlcv("BTC/USDT", "1m", limit=3)
    assert len(candles) == 3
    assert candles[-1][4] > 0  # last close


async def test_datafetcher_testnet_uses_spot_not_futures():
    # Guards the DataFetcher bug: testnet sandbox must reach the SPOT testnet,
    # not the futures testnet (dapi/fapi), which is unavailable and would raise.
    from data.fetcher import DataFetcher
    f = DataFetcher(exchange_id="binance", testnet=True)
    try:
        candles = await f.fetch_ohlcv("BTC/USDT", "1m", limit=3)
        assert len(candles) == 3
    finally:
        await f.close()


async def test_order_lifecycle_market_buy_oco_protect_cancel(exchange):
    # The full go-live execution path that mocks hid: a real MARKET BUY, then a
    # real OCO protective order (TP + SL), then cancel + sell back to flat.
    sym = "BTC/USDT"
    px = float((await exchange.fetch_ohlcv(sym, "1m", limit=1))[-1][4])
    qty = round(25.0 / px, 6)  # ~$25 notional clears minNotional ($10)

    buy = Order(id=str(uuid.uuid4()), symbol=sym, side="BUY", type="MARKET",
                quantity=qty, price=None, status="PENDING", exchange_order_id=None)
    filled = await exchange.place_order(buy, current_price=px)
    assert filled.status in ("FILLED", "OPEN")

    prot = await exchange.protect_position(
        sym, side="BUY", quantity=qty,
        take_profit=round(px * 1.02, 2), stop_loss=round(px * 0.98, 2),
        current_price=px,
    )
    assert prot is not None
    assert prot.type == "OCO"
    assert prot.status == "OPEN"
    assert prot.exchange_order_id  # an orderListId came back

    # Cleanup: cancel the OCO list, then market-sell the position back to flat.
    try:
        await exchange._exchange.private_delete_orderlist(
            {"symbol": exchange._exchange.market_id(sym), "orderListId": int(prot.exchange_order_id)}
        )
    except Exception:
        pass  # best-effort; a partial fill or already-gone list is fine on testnet
    sell = Order(id=str(uuid.uuid4()), symbol=sym, side="SELL", type="MARKET",
                 quantity=qty, price=None, status="PENDING", exchange_order_id=None)
    await exchange.place_order(sell, current_price=px)
