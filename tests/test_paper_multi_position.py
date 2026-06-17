"""Stage 1 of plan B: PaperExchange must hold independent positions for two
strategies on the SAME symbol, each with its own TP/SL, closed independently.
Foundation for running ema_cross + rsi_macd concurrently on one spot account."""
import pytest
from core.models import Order
from exchange.paper import PaperExchange


def _buy(strategy_id: str) -> Order:
    return Order(id=f"{strategy_id}-1", symbol="BTC/USDT", side="BUY", type="MARKET",
                 quantity=0.01, price=100.0, status="PENDING", exchange_order_id=None,
                 strategy_id=strategy_id)


@pytest.mark.asyncio
async def test_two_strategies_independent_positions_same_symbol():
    ex = PaperExchange(initial_balance={"USDT": 10000.0})

    await ex.place_order(_buy("ema_cross"), current_price=100.0)
    await ex.protect_position("BTC/USDT", "BUY", 0.01, take_profit=110.0, stop_loss=90.0,
                              strategy_id="ema_cross")
    await ex.place_order(_buy("rsi_macd"), current_price=100.0)
    await ex.protect_position("BTC/USDT", "BUY", 0.01, take_profit=200.0, stop_loss=50.0,
                              strategy_id="rsi_macd")

    positions = await ex.get_positions()
    assert len(positions) == 2, "two strategies should hold two independent positions"
    assert {p.strategy_id for p in positions} == {"ema_cross", "rsi_macd"}

    # Price spikes to 115: ema_cross TP (110) hits; rsi_macd TP (200) does not.
    fills = await ex.tick("BTC/USDT", high=115.0, low=108.0, close=112.0)
    assert len(fills) == 1
    assert fills[0].strategy_id == "ema_cross"

    remaining = await ex.get_positions()
    assert len(remaining) == 1
    assert remaining[0].strategy_id == "rsi_macd"

    # The closed trade is attributed to ema_cross.
    log = ex.get_trade_log()
    assert len(log) == 1
    assert log[0].strategy_id == "ema_cross"
    assert log[0].exit_reason == "TP"
