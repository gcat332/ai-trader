import pytest
from core.live_controller import LiveEngineController
from core.models import Position


class FakeExchange:
    def __init__(self, positions):
        self._positions = list(positions)
        self.placed = []

    async def get_positions(self):
        return list(self._positions)

    async def place_order(self, order):
        self.placed.append(order)
        # simulate a full reduce-only close: drop the matching position
        self._positions = [
            p for p in self._positions
            if not (p.symbol == order.symbol and _closes(p, order))
        ]
        return order


def _closes(pos, order):
    want = "SELL" if pos.side == "LONG" else "BUY"
    return order.side == want


def _pos(side, sym="BTC/USDT", qty=0.1):
    return Position(symbol=sym, side=side, entry_price=60000.0, quantity=qty,
                    unrealized_pnl=0.0, take_profit=None, stop_loss=None,
                    mode="FUTURES", leverage=5, liquidation_price=None)


def _ctrl(positions):
    ex = FakeExchange(positions)

    class _Eng:
        exchange = ex
    c = LiveEngineController(_Eng(), repo=None, daily_start_balance=0.0)
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
