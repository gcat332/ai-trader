import pytest
from core.live_controller import LiveEngineController
from core.models import Position


class FakeExchange:
    def __init__(self, positions, *, remove_on_place=True):
        self._positions = list(positions)
        self._remove_on_place = remove_on_place
        self.placed = []

    async def get_positions(self):
        return list(self._positions)

    async def place_order(self, order):
        self.placed.append(order)
        if not self._remove_on_place:
            return order
        # simulate a full reduce-only close: drop the matching position
        self._positions = [
            p for p in self._positions
            if not (p.symbol == order.symbol and _closes(p, order))
        ]
        return order


def _closes(pos, order):
    want = "SELL" if pos.side == "LONG" else "BUY"
    return order.side == want


def _pos(side, sym="BTC/USDT", qty=0.1, strategy_id="loop1:ema_cross"):
    return Position(symbol=sym, side=side, entry_price=60000.0, quantity=qty,
                    unrealized_pnl=0.0, take_profit=None, stop_loss=None,
                    mode="FUTURES", strategy_id=strategy_id, leverage=5,
                    liquidation_price=None)


def _engine(exchange):
    class _Eng:
        pass
    e = _Eng()
    e.exchange = exchange
    return e


def _ctrl(positions, *, exchange=None, extra_engines=None):
    ex = exchange or FakeExchange(positions)
    c = LiveEngineController(_engine(ex), repo=None, daily_start_balance=0.0,
                             extra_engines=extra_engines)
    return c, ex


@pytest.mark.asyncio
async def test_close_short_sends_buy_reduce_only():
    c, ex = _ctrl([_pos("SHORT")])
    res = await c.close_position("BTC/USDT", side="SHORT")
    assert res["status"] == "closed"
    assert ex.placed[0].side == "BUY"
    assert ex.placed[0].reduce_only is True


@pytest.mark.asyncio
async def test_close_resolves_correct_leg_when_both_sides_open():
    c, ex = _ctrl([_pos("LONG"), _pos("SHORT")])
    res = await c.close_position("BTC/USDT", side="LONG")
    assert res["status"] == "closed"
    assert ex.placed[0].side == "SELL"
    # the short leg survived
    remaining = await ex.get_positions()
    assert [p.side for p in remaining] == ["SHORT"]


@pytest.mark.asyncio
async def test_close_not_found_is_reported():
    c, _ = _ctrl([_pos("LONG")])
    res = await c.close_position("ETH/USDT", side="LONG")
    assert res["status"] == "not_found"


@pytest.mark.asyncio
async def test_flatten_closes_all_loops():
    c, ex = _ctrl([_pos("LONG", "BTC/USDT"), _pos("SHORT", "ETH/USDT")])
    results = await c.flatten()
    assert {r["status"] for r in results} == {"closed"}
    assert len(ex.placed) == 2
    assert await ex.get_positions() == []


@pytest.mark.asyncio
async def test_flatten_closes_each_engine_position_on_own_exchange():
    ex1 = FakeExchange([_pos("LONG", "BTC/USDT", strategy_id="loop1:ema_cross")])
    ex2 = FakeExchange([_pos("SHORT", "ETH/USDT", strategy_id="loop2:rsi_macd")])
    c, _ = _ctrl([], exchange=ex1, extra_engines=[_engine(ex2)])

    results = await c.flatten()

    assert [r["status"] for r in results] == ["closed", "closed"]
    assert [o.symbol for o in ex1.placed] == ["BTC/USDT"]
    assert [o.symbol for o in ex2.placed] == ["ETH/USDT"]
    assert await ex1.get_positions() == []
    assert await ex2.get_positions() == []


@pytest.mark.asyncio
async def test_close_position_reports_partial_when_readback_has_residual():
    c, _ = _ctrl(
        [_pos("LONG", "BTC/USDT", qty=0.25)],
        exchange=FakeExchange([_pos("LONG", "BTC/USDT", qty=0.25)], remove_on_place=False),
    )

    result = await c.close_position("BTC/USDT", side="LONG")

    assert result["status"] == "partial"
    assert result["residual_qty"] > 0


@pytest.mark.asyncio
async def test_move_to_breakeven_reports_unsupported_without_exchange_method():
    c, _ = _ctrl([_pos("LONG", "BTC/USDT")])

    result = await c.move_to_breakeven("BTC/USDT", side="LONG")

    assert result == {"status": "unsupported", "symbol": "BTC/USDT", "side": "LONG"}
