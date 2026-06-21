# Telegram Futures UX (§11) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Telegram bot futures-aware (long+short, leverage, liquidation) and safer to operate — direction-aware views, a leverage-aware proactive liquidation warning, position-identity close, inline action buttons with confirmation, and a `/flatten` panic — by extending the existing `notifier/telegram.py` formatters and `EngineController` plumbing.

**Architecture:** Extend, do not rewrite. The `Position` model already carries `side`/`mode`/`leverage`/`entry_price`/`liquidation_price`; `core/live_controller.py` currently drops them. We widen the controller's position dicts, then extend the formatters/commands that already consume them. The proactive liq warning fires from the existing `core/trading_loop.py` poll (it already holds `positions_now` + `last_close` mark price). Inline buttons attach to the **wired** surfaces — `/open_positions` output and the liq-warning push — because the per-event `on_signal`/`on_order_filled` hooks are currently **unwired** (dormant since the telegram-first migration); the entry/order formatters are still made futures-aware (they are unit-tested and ready when emit is wired), but no button depends on them.

**Tech Stack:** Python 3.12, `python-telegram-bot` (Application/CommandHandler/CallbackQueryHandler, InlineKeyboardMarkup/InlineKeyboardButton/BotCommand), pytest + pytest-asyncio, `unittest.mock` (AsyncMock/MagicMock).

## Global Constraints

- **Spot path byte-for-byte unchanged.** Every futures field renders only when a position's `mode == "FUTURES"`; spot positions (`mode="SPOT"`, `leverage=1`, `liquidation_price=None`) produce today's exact strings. Tests assert spot output unchanged.
- **Real money stays OFF** (`LIVE_TRADING_ENABLED=false`). This milestone is notification/control UX; validated on paper + testnet.
- **Position identity:** every close/breakeven action addresses a specific position by `symbol + side` (+ `loop_id` when needed), never a bare symbol — long and short can coexist on one symbol in the 4-loop layout.
- **Closes are `reduce_only=True`** and derive side from the position: LONG→SELL, SHORT→BUY.
- **Surfacing depth = Basic:** show `side / leverage / liquidation_price / initial_margin` only. Funding rate, ROE, and margin-ratio are out of scope.
- **Liq warning is leverage-aware, price-distance, two-tier** (soft once / hard repeating). NOT a single 10%-of-liq buffer.
- **`/menu` reply keyboard is cut.** `set_my_commands` is trimmed to ~8 core commands. The `SL→BE` button is default-off-gated with the partial-TP feature.
- **Auth:** every new command and every callback reuses the existing `_authorized` / `_reject_if_unauthorized` gate.
- Test runner: `.venv/bin/python -m pytest`. Baseline before Task 1: **527 passed / 6 skipped**.
- Implementer = codex; Claude = staff review (Opus on the close/liq-warning safety paths) before merge.

---

### Task 1: Controller position-dict widening

**Files:**
- Modify: `core/live_controller.py` (add `_position_dict` staticmethod; use it at the 3 sites — `get_status` ~97, `get_strategies` ~166, `get_strategy_status` ~201; add `market` label to strategy summaries ~149 and ~184)
- Modify: `notifier/engine_controller.py` (update `get_status` docstring to document widened dict)
- Test: `tests/test_live_controller_position_dict.py` (create)

**Interfaces:**
- Produces: `LiveEngineController._position_dict(p) -> dict` with keys `symbol, quantity, unrealized_pnl, side, mode, leverage, entry_price, liquidation_price, initial_margin`. `initial_margin = entry_price * quantity / leverage` (leverage≥1). Strategy summary dicts gain `market: "SPOT"|"FUTURES"` (from `cfg.market`).
- Consumes (later tasks): formatters in Tasks 2/3 read these keys; close/flatten in Task 4 read `side`/`mode` off the live `Position` objects (not these dicts).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_live_controller_position_dict.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_live_controller_position_dict.py -v`
Expected: FAIL — `AttributeError: type object 'LiveEngineController' has no attribute '_position_dict'`

- [ ] **Step 3: Add the helper and use it at all three sites**

In `core/live_controller.py`, add the staticmethod (near the other staticmethods, e.g. after `_runtime_strategy_ids`):

```python
    @staticmethod
    def _position_dict(p) -> dict:
        leverage = getattr(p, "leverage", 1) or 1
        entry = getattr(p, "entry_price", 0.0) or 0.0
        qty = p.quantity
        return {
            "symbol": p.symbol,
            "quantity": qty,
            "unrealized_pnl": p.unrealized_pnl,
            "side": getattr(p, "side", None),
            "mode": getattr(p, "mode", "SPOT"),
            "leverage": leverage,
            "entry_price": entry,
            "liquidation_price": getattr(p, "liquidation_price", None),
            "initial_margin": (entry * qty) / leverage,
        }
```

Replace the inline dict at `get_status` (the `"open_positions": [...]` comprehension):

```python
            "open_positions": [self._position_dict(p) for p in positions],
```

Replace the comprehension in `get_strategies` (keep the `if getattr(p, "strategy_id", ...) in ...` filter):

```python
                "open_positions": [
                    self._position_dict(p)
                    for p in await r.engine.exchange.get_positions()
                    if getattr(p, "strategy_id", r.config.strategy_instance_id) in self._runtime_strategy_ids(r)
                ],
```

And in `get_strategies` add the loop-level market label (in the same dict literal, e.g. after `"mode": r.config.mode,`):

```python
                "market": (getattr(r.config, "market", "spot") or "spot").upper(),
```

Replace the comprehension in `get_strategy_status` likewise:

```python
                "open_positions": [
                    self._position_dict(p)
                    for p in positions
                    if getattr(p, "strategy_id", cfg.strategy_instance_id) in strategy_ids
                ],
```

And add to that dict literal (after `"mode": cfg.mode,`):

```python
                "market": (getattr(cfg, "market", "spot") or "spot").upper(),
```

- [ ] **Step 4: Update the ABC docstring**

In `notifier/engine_controller.py`, change the `get_status` docstring:

```python
    @abstractmethod
    async def get_status(self) -> dict:
        """Return dict with keys: running (bool), strategy_id (str),
        open_positions (list of dicts with symbol, quantity, unrealized_pnl,
        side, mode, leverage, entry_price, liquidation_price, initial_margin)."""
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_live_controller_position_dict.py tests/test_telegram.py tests/test_telegram_multiloop.py -v`
Expected: PASS (new tests green; existing telegram tests still pass — the extra dict keys are additive).

- [ ] **Step 6: Commit**

```bash
git add core/live_controller.py notifier/engine_controller.py tests/test_live_controller_position_dict.py
git commit -m "feat(telegram): widen controller position dicts with futures fields"
```

---

### Task 2: Direction-aware entry/order formatters

**Files:**
- Modify: `notifier/telegram.py` (`format_signal_alert` ~39, `format_order_alert` ~133)
- Test: `tests/test_telegram_futures_format.py` (create)

**Interfaces:**
- Produces: `format_signal_alert(signal, *, mode="SPOT", leverage=1) -> str` and `format_order_alert(order, entry_price, realized_pnl, *, position=None) -> str` where `position` is a widened position dict (from Task 1) or `None`.
- Note: these emit paths (`on_signal`/`on_order_filled`) are currently dormant (unwired). The formatters are still made futures-aware and unit-tested so they are correct when emit is wired; no later task depends on them being emitted.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_telegram_futures_format.py
from datetime import datetime, timezone
from core.models import Signal, Order
from notifier.telegram import format_signal_alert, format_order_alert


def _sig(side="BUY"):
    return Signal(
        symbol="BTC/USDT", side=side, entry_price=60000.0,
        take_profit=63000.0, stop_loss=58000.0, trailing_sl=False,
        confidence=0.8, strategy_id="trend", timestamp=datetime.now(timezone.utc),
    )


def test_signal_alert_spot_unchanged_no_leverage_line():
    text = format_signal_alert(_sig("BUY"))  # default mode=SPOT
    assert "Leverage" not in text
    assert "LONG" not in text  # spot keeps BUY/SELL wording
    assert "BUY" in text


def test_signal_alert_futures_shows_direction_and_leverage():
    text = format_signal_alert(_sig("BUY"), mode="FUTURES", leverage=5)
    assert "LONG" in text
    assert "5x" in text  # leverage rendered


def test_signal_alert_futures_sell_is_short():
    text = format_signal_alert(_sig("SELL"), mode="FUTURES", leverage=3)
    assert "SHORT" in text


def test_order_alert_spot_unchanged():
    order = Order(id="o1", symbol="BTC/USDT", side="SELL", type="MARKET",
                  quantity=0.1, price=61000.0, status="FILLED", exchange_order_id="x")
    text = format_order_alert(order, entry_price=60000.0, realized_pnl=100.0)
    assert "Liq" not in text
    assert "Leverage" not in text


def test_order_alert_futures_shows_liq_and_margin():
    order = Order(id="o1", symbol="BTC/USDT", side="SELL", type="MARKET",
                  quantity=0.1, price=61000.0, status="FILLED", exchange_order_id="x")
    pos = {"mode": "FUTURES", "side": "LONG", "leverage": 5,
           "liquidation_price": 54000.0, "initial_margin": 1200.0}
    text = format_order_alert(order, entry_price=60000.0, realized_pnl=100.0, position=pos)
    assert "Liq" in text and "54,000" in text
    assert "5x" in text
    assert "1,200" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_telegram_futures_format.py -v`
Expected: FAIL — `TypeError: format_signal_alert() got an unexpected keyword argument 'mode'`

- [ ] **Step 3: Implement the futures-aware branches**

Replace `format_signal_alert` in `notifier/telegram.py`:

```python
def format_signal_alert(signal: Signal, *, mode: str = "SPOT", leverage: int = 1) -> str:
    futures = mode == "FUTURES"
    if futures:
        emoji, direction = ("🟢", "LONG") if signal.side == "BUY" else ("🔴", "SHORT")
        head = f"{emoji} {direction} {leverage}x · {signal.strategy_id}"
    else:
        emoji = "🟢" if signal.side == "BUY" else "🔴"
        head = f"{emoji} Signal · {signal.strategy_id}"
    tp = f"{signal.take_profit:,.0f}" if signal.take_profit else "—"
    sl = f"{signal.stop_loss:,.0f}" if signal.stop_loss else "—"
    side_word = signal.side if not futures else ("LONG" if signal.side == "BUY" else "SHORT")
    text = (
        f"{head}\n"
        f"{_thai_datetime(signal.timestamp)}\n\n"
        f"{side_word} {signal.symbol} @ {signal.entry_price:,.0f}\n"
        f"TP: {tp}  |  SL: {sl}\n"
        f"Confidence: {signal.confidence:.0%}"
    )
    if futures:
        text += f"\nLeverage: {leverage}x"
    if signal.narrative:
        short = " | ".join(signal.narrative.split(" | ")[:2])
        text += f"\n{short}"
    return text
```

> ponytail: spot branch reproduces the old header/side wording exactly so the spot golden tests in `tests/test_telegram.py` stay green.

Replace `format_order_alert`:

```python
def format_order_alert(order: Order, entry_price: float, realized_pnl: float,
                       *, position: dict | None = None) -> str:
    emoji = "🟢" if realized_pnl >= 0 else "🔴"
    sign = "+" if realized_pnl >= 0 else ""
    pct = ((order.price - entry_price) / entry_price * 100) if entry_price else 0
    text = (
        f"{emoji} Order Filled · {order.strategy_id or 'unknown'}\n"
        f"{_thai_datetime()}\n\n"
        f"{order.symbol} {order.side} @ {order.price:,.0f}\n"
        f"PnL: {sign}${realized_pnl:.2f} ({sign}{pct:.1f}%)"
    )
    if position and position.get("mode") == "FUTURES":
        lev = position.get("leverage", 1)
        liq = position.get("liquidation_price")
        margin = position.get("initial_margin")
        text += f"\nLeverage: {lev}x"
        if liq is not None:
            text += f"\nLiq: {liq:,.0f}"
        if margin is not None:
            text += f"\nMargin: {margin:,.0f}"
    return text
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_telegram_futures_format.py tests/test_telegram.py -v`
Expected: PASS (new + all existing spot formatter tests).

- [ ] **Step 5: Commit**

```bash
git add notifier/telegram.py tests/test_telegram_futures_format.py
git commit -m "feat(telegram): direction-aware entry/order formatters (spot unchanged)"
```

---

### Task 3: Futures-aware position list + status

**Files:**
- Modify: `notifier/telegram.py` (`format_strategy_list` ~170, `cmd_open_positions` ~574)
- Test: `tests/test_telegram_futures_positions.py` (create)

**Interfaces:**
- Consumes: widened position dicts from Task 1 (`side, mode, leverage, liquidation_price, initial_margin`) and the strategy `market` label.
- Produces: `_format_position_line(p: dict) -> str` (module-level helper) rendering a single position; futures line is liq-first and dense, spot line unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_telegram_futures_positions.py
from notifier.telegram import format_strategy_list, _format_position_line


def test_position_line_spot_unchanged():
    p = {"symbol": "BTC/USDT", "quantity": 0.1, "unrealized_pnl": 5.0, "mode": "SPOT"}
    line = _format_position_line(p)
    assert "BTC/USDT" in line and "0.1" in line and "5.0" in line
    assert "liq" not in line.lower()


def test_position_line_futures_shows_side_lev_liq_margin_first():
    p = {"symbol": "BTC/USDT", "quantity": 0.1, "unrealized_pnl": 8.0,
         "mode": "FUTURES", "side": "SHORT", "leverage": 3,
         "liquidation_price": 71240.0, "initial_margin": 2000.0}
    line = _format_position_line(p)
    assert "SHORT" in line
    assert "3x" in line
    assert "71,240" in line          # liq present
    assert "2,000" in line           # margin present
    # liq appears before pnl (survival number is skimmable)
    assert line.index("71,240") < line.index("8.0")


def test_strategy_list_labels_market():
    strategies = [{
        "loop_id": "loop3", "strategy_name": "trend", "mode": "LIVE",
        "market": "FUTURES", "running": True, "symbol": "BTC/USDT",
        "timeframe": "1h", "allocation_pct": 0.5, "open_order_count": 0,
        "open_positions": [],
    }]
    text = format_strategy_list(strategies)
    assert "FUTURES" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_telegram_futures_positions.py -v`
Expected: FAIL — `ImportError: cannot import name '_format_position_line'`

- [ ] **Step 3: Add the helper, use it in the formatters**

In `notifier/telegram.py`, add a module-level helper (near `_money`):

```python
def _format_position_line(p: dict) -> str:
    sym = p["symbol"]
    qty = p["quantity"]
    upnl = p.get("unrealized_pnl", 0.0)
    if p.get("mode") == "FUTURES":
        side = p.get("side") or "?"
        lev = p.get("leverage", 1)
        liq = p.get("liquidation_price")
        margin = p.get("initial_margin")
        liq_txt = f"liq {liq:,.0f}" if liq is not None else "liq —"
        margin_txt = f"margin {margin:,.0f}" if margin is not None else "margin —"
        return f"  • {sym} {side} {lev}x · {liq_txt} · qty={qty} · {margin_txt} · uPnL ${upnl:.1f}"
    return f"  • {sym} qty={qty} unrealized=${upnl:.2f}"
```

> ponytail: spot branch is the exact old string from `format_strategy_list`/`cmd_open_positions` so spot output is byte-for-byte.

In `format_strategy_list`, where it currently does:

```python
        if positions:
            lines.append("Open positions:")
            lines.extend(
                f"  • {p['symbol']} qty={p['quantity']} unrealized=${p['unrealized_pnl']:.2f}"
                for p in positions
            )
```

replace the `lines.extend(...)` with:

```python
            lines.extend(_format_position_line(p) for p in positions)
```

And add the market label to the per-loop header block. Where it builds the loop lines (the `f"{state_icon} {s['loop_id']} / {s['strategy_name']}"` block), add right after the `Mode:` line:

```python
            *([f"Market: {s['market']}"] if s.get("market") else []),
```

In `cmd_open_positions`, replace:

```python
        await update.message.reply_text("\n".join(
            f"{p['symbol']} qty={p['quantity']} unrealized={p['unrealized_pnl']:.2f}"
            for p in positions
        ))
```

with:

```python
        await update.message.reply_text("\n".join(
            _format_position_line(p).lstrip("• ").strip() for p in positions
        ))
```

> Note: `cmd_open_positions` keeps its flat (no `  • `) layout; `.lstrip("• ").strip()` removes the bullet prefix the shared helper adds.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_telegram_futures_positions.py tests/test_telegram.py tests/test_telegram_multiloop.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add notifier/telegram.py tests/test_telegram_futures_positions.py
git commit -m "feat(telegram): futures-aware position lines (liq-first) + market label"
```

---

### Task 4: Close-by-identity (short fix + read-back) + flatten()

**Files:**
- Modify: `core/live_controller.py` (`close_position` ~220; add `flatten`, `move_to_breakeven`)
- Modify: `notifier/engine_controller.py` (update `close_position` signature/docstring; add `flatten`, `move_to_breakeven` abstract methods)
- Test: `tests/test_close_identity.py` (create)

**Interfaces:**
- Produces:
  - `close_position(symbol, *, side=None, loop_id=None) -> dict` → `{"status": "closed"|"already_flat"|"partial"|"not_found", "symbol": str, "side": str|None, "residual_qty": float}`.
  - `flatten() -> list[dict]` → one result dict (same shape) per attempted position.
  - `move_to_breakeven(symbol, *, side=None, loop_id=None) -> dict` → `{"status": "moved"|"not_found"|"unsupported"|"wrong_side", "symbol": str, "side": str|None}`.
- Consumes: live `Position` objects from `exchange.get_positions()` (have `.side`, `.mode`, `.quantity`, `.entry_price`); exchange `place_order`, optional `move_stop_to_breakeven` (Task uses `hasattr`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_close_identity.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_close_identity.py -v`
Expected: FAIL — `close_position()` returns `bool` and ignores `side`; `place_order` order has no `reduce_only=True`; `flatten` undefined.

- [ ] **Step 3: Implement close-by-identity + read-back + flatten + breakeven**

In `core/live_controller.py`, replace `close_position` and add the new methods:

```python
    @staticmethod
    def _closing_side(position_side: str) -> str:
        return "SELL" if position_side == "LONG" else "BUY"

    def _match(self, positions, symbol, side, loop_id):
        def ok(p):
            if not (p.symbol == symbol or p.symbol.startswith(symbol)):
                return False
            if side is not None and getattr(p, "side", None) != side:
                return False
            if loop_id is not None and not getattr(p, "strategy_id", "").startswith(f"{loop_id}:"):
                return False
            return True
        return [p for p in positions if ok(p)]

    async def _close_one(self, pos) -> dict:
        order = Order(
            id=str(uuid.uuid4()),
            symbol=pos.symbol,
            side=self._closing_side(getattr(pos, "side", "LONG")),
            type="MARKET",
            quantity=pos.quantity,
            price=None,
            status="PENDING",
            exchange_order_id=None,
            reduce_only=True,
        )
        await self._engine.exchange.place_order(order)
        # Read back: confirm the position is gone. A reduce-only on an
        # already-flat position (-2022) is success-equivalent. closePosition
        # brackets auto-cancel on flat, so no separate resting-order sweep here.
        after = await self._engine.exchange.get_positions()
        residual = next(
            (p for p in after
             if p.symbol == pos.symbol and getattr(p, "side", None) == getattr(pos, "side", None)),
            None,
        )
        if residual is None:
            return {"status": "closed", "symbol": pos.symbol,
                    "side": getattr(pos, "side", None), "residual_qty": 0.0}
        return {"status": "partial", "symbol": pos.symbol,
                "side": getattr(pos, "side", None), "residual_qty": residual.quantity}

    async def close_position(self, symbol: str, *, side: str | None = None,
                             loop_id: str | None = None) -> dict:
        positions = await self._engine.exchange.get_positions()
        matches = self._match(positions, symbol, side, loop_id)
        if not matches:
            return {"status": "not_found", "symbol": symbol, "side": side, "residual_qty": 0.0}
        # Close every matching leg (identity-scoped; usually one).
        results = [await self._close_one(p) for p in matches]
        return results[0] if len(results) == 1 else {
            "status": "closed" if all(r["status"] == "closed" for r in results) else "partial",
            "symbol": symbol, "side": side,
            "residual_qty": sum(r["residual_qty"] for r in results),
        }

    async def flatten(self) -> list[dict]:
        results = []
        for e in self._engines:
            for p in await e.exchange.get_positions():
                results.append(await self._close_one(p))
        return results

    async def move_to_breakeven(self, symbol: str, *, side: str | None = None,
                                loop_id: str | None = None) -> dict:
        positions = await self._engine.exchange.get_positions()
        matches = self._match(positions, symbol, side, loop_id)
        if not matches:
            return {"status": "not_found", "symbol": symbol, "side": side}
        pos = matches[0]
        ex = self._engine.exchange
        if not hasattr(ex, "move_stop_to_breakeven"):
            return {"status": "unsupported", "symbol": pos.symbol, "side": pos.side}
        await ex.move_stop_to_breakeven(
            symbol=pos.symbol, side=pos.side, quantity=pos.quantity,
            entry_price=pos.entry_price, old_stop_order_id=None,
        )
        return {"status": "moved", "symbol": pos.symbol, "side": pos.side}
```

- [ ] **Step 4: Update the ABC**

In `notifier/engine_controller.py`, replace the `close_position` abstractmethod and add two more:

```python
    @abstractmethod
    async def close_position(self, symbol: str, *, side: str | None = None,
                             loop_id: str | None = None) -> dict:
        """Close the identity-matched position (symbol [+ side + loop_id]).
        reduce-only; side derived from the position (LONG→SELL, SHORT→BUY).
        Returns {status, symbol, side, residual_qty}."""

    @abstractmethod
    async def flatten(self) -> list[dict]:
        """Close every open position across all loops (reduce-only). Returns
        one result dict per position."""

    @abstractmethod
    async def move_to_breakeven(self, symbol: str, *, side: str | None = None,
                                loop_id: str | None = None) -> dict:
        """Move the matched position's stop to entry (breakeven). Returns
        {status, symbol, side}."""
```

> Note: `core/models.Order` must accept `reduce_only` (it already does — added in M1 §5.1). If a second `EngineController` subclass exists outside `core/live_controller.py` that does not implement `flatten`/`move_to_breakeven`, add the methods there too; `api/main.py` builds its own ad-hoc controller object (not subclassing the ABC) and does not call these, so it is unaffected.

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_close_identity.py tests/test_telegram.py -v`
Expected: PASS. (The existing `test_handle_close_command` may assert on the old bool return — update its assertion to the new dict in this task if it fails.)

- [ ] **Step 6: Commit**

```bash
git add core/live_controller.py notifier/engine_controller.py tests/test_close_identity.py tests/test_telegram.py
git commit -m "feat(telegram): close-by-identity (short fix + read-back) + flatten + move_to_breakeven"
```

---

### Task 5: Leverage-aware two-tier liquidation warning

**Files:**
- Modify: `notifier/telegram.py` (add `liq_warning_tier`, `format_liq_warning`, `TelegramNotifier.maybe_warn_liquidation`)
- Modify: `core/trading_loop.py` (call the warning after `positions_now`, ~167)
- Test: `tests/test_liq_warning.py` (create)

**Interfaces:**
- Produces:
  - `liq_warning_tier(mark: float, liq: float, leverage: int) -> str` → `"none"|"soft"|"hard"` (price-distance `abs(mark-liq)/mark` vs leverage-tiered bands).
  - `format_liq_warning(p: dict, mark: float, distance_pct: float) -> str` (self-contained: side, leverage, mark, liq, distance%, uPnL).
  - `TelegramNotifier.maybe_warn_liquidation(positions: list[dict], mark: float) -> None` (holds dedup state in `self._liq_soft_warned: set[str]`).
- Consumes: widened position dicts (Task 1) — `mode, side, leverage, liquidation_price, symbol, unrealized_pnl`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_liq_warning.py
import pytest
from unittest.mock import AsyncMock
from notifier.telegram import liq_warning_tier, TelegramNotifier
from notifier.engine_controller import EngineController


def test_tier_low_leverage_bands():
    # 5x: soft 8%, hard 4%. liq=50000.
    assert liq_warning_tier(mark=60000, liq=50000, leverage=5) == "none"   # 16.7%
    assert liq_warning_tier(mark=54000, liq=50000, leverage=5) == "soft"   # 7.4%
    assert liq_warning_tier(mark=51500, liq=50000, leverage=5) == "hard"   # 2.9%


def test_tier_high_leverage_bands():
    # 20x: soft 2%, hard 1%.
    assert liq_warning_tier(mark=51500, liq=50000, leverage=20) == "none"  # 2.9%
    assert liq_warning_tier(mark=50800, liq=50000, leverage=20) == "soft"  # 1.57%
    assert liq_warning_tier(mark=50300, liq=50000, leverage=20) == "hard"  # 0.6%


def _notifier():
    n = TelegramNotifier("t", "1", AsyncMock(spec=EngineController))
    n.send = AsyncMock()
    return n


def _fpos(liq, **kw):
    base = dict(symbol="BTC/USDT", mode="FUTURES", side="LONG", leverage=5,
                liquidation_price=liq, unrealized_pnl=-3.0, quantity=0.1)
    base.update(kw)
    return base


@pytest.mark.asyncio
async def test_soft_warns_once_then_rearms():
    n = _notifier()
    await n.maybe_warn_liquidation([_fpos(50000)], mark=54000)   # soft → warn
    await n.maybe_warn_liquidation([_fpos(50000)], mark=53900)   # still soft → silent
    assert n.send.await_count == 1
    await n.maybe_warn_liquidation([_fpos(50000)], mark=60000)   # exits band → re-arm
    await n.maybe_warn_liquidation([_fpos(50000)], mark=54000)   # soft again → warn
    assert n.send.await_count == 2


@pytest.mark.asyncio
async def test_hard_repeats_every_poll():
    n = _notifier()
    await n.maybe_warn_liquidation([_fpos(50000)], mark=51500)   # hard
    await n.maybe_warn_liquidation([_fpos(50000)], mark=51400)   # hard again
    assert n.send.await_count == 2


@pytest.mark.asyncio
async def test_spot_and_no_liq_skipped():
    n = _notifier()
    await n.maybe_warn_liquidation([_fpos(50000, mode="SPOT")], mark=51000)
    await n.maybe_warn_liquidation([_fpos(None)], mark=51000)
    assert n.send.await_count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_liq_warning.py -v`
Expected: FAIL — `cannot import name 'liq_warning_tier'`.

- [ ] **Step 3: Implement the tier table, formatter, and warning method**

In `notifier/telegram.py`, add module-level:

```python
# Leverage-tiered liquidation bands as price-distance |mark-liq|/mark.
# (soft = warn once, hard = repeat every poll). Override via env if needed.
_LIQ_BANDS = [
    (5,  0.08, 0.04),
    (10, 0.04, 0.02),
    (20, 0.02, 0.01),
]
_LIQ_BANDS_DEFAULT = (0.01, 0.005)  # > 20x


def _liq_bands_for(leverage: int) -> tuple[float, float]:
    for cap, soft, hard in _LIQ_BANDS:
        if leverage <= cap:
            return soft, hard
    return _LIQ_BANDS_DEFAULT


def liq_warning_tier(mark: float, liq: float, leverage: int) -> str:
    if not liq or not mark:
        return "none"
    distance = abs(mark - liq) / mark
    soft, hard = _liq_bands_for(leverage)
    if distance <= hard:
        return "hard"
    if distance <= soft:
        return "soft"
    return "none"


def format_liq_warning(p: dict, mark: float, distance_pct: float) -> str:
    return (
        f"⚠️ NEAR LIQUIDATION · {p['symbol']} {p.get('side')} {p.get('leverage')}x\n"
        f"Mark: {mark:,.0f}  |  Liq: {p['liquidation_price']:,.0f}\n"
        f"Distance: {distance_pct:.2%}\n"
        f"uPnL: ${p.get('unrealized_pnl', 0.0):.2f}"
    )
```

Add to `TelegramNotifier.__init__` (after `self._health_monitor = None`):

```python
        self._liq_soft_warned: set[str] = set()
```

Add the method to `TelegramNotifier`:

```python
    async def maybe_warn_liquidation(self, positions: list[dict], mark: float) -> None:
        """Fire a near-liquidation alert per the leverage-tiered two-tier model.
        Soft tier warns once until the position exits the band (re-arm); hard
        tier repeats every poll. Futures-only; spot/None-liq skipped."""
        for p in positions:
            if p.get("mode") != "FUTURES":
                continue
            liq = p.get("liquidation_price")
            if not liq:
                continue
            key = f"{p['symbol']}:{p.get('side')}"
            tier = liq_warning_tier(mark, liq, p.get("leverage", 1) or 1)
            if tier == "none":
                self._liq_soft_warned.discard(key)
                continue
            if tier == "soft":
                if key in self._liq_soft_warned:
                    continue
                self._liq_soft_warned.add(key)
            # hard: never dedup (fall through and warn every poll)
            distance_pct = abs(mark - liq) / mark
            await self.send(format_liq_warning(p, mark, distance_pct))
```

- [ ] **Step 4: Wire it into the trading loop**

In `core/trading_loop.py`, right after the `outcome_tracker.snapshot(...)` line (~167), add:

```python
                    if notifier is not None and hasattr(notifier, "maybe_warn_liquidation"):
                        await notifier.maybe_warn_liquidation(
                            [LiveEngineController._position_dict(p) for p in positions_now],
                            last_close,
                        )
```

Add the import near the top of `core/trading_loop.py` (with the other `core` imports):

```python
from core.live_controller import LiveEngineController
```

> ponytail: reuse `_position_dict` so the warning sees the same fields the commands do — one source of truth. `last_close` is the mark price the loop already computed.

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_liq_warning.py tests/test_trading_loop.py -v`
Expected: PASS. (If `tests/test_trading_loop.py` does not exist, run only the first file; verify no import cycle: `core.trading_loop` importing `core.live_controller` is one-directional — `live_controller` does not import `trading_loop`.)

- [ ] **Step 6: Commit**

```bash
git add notifier/telegram.py core/trading_loop.py tests/test_liq_warning.py
git commit -m "feat(telegram): leverage-aware two-tier proactive liquidation warning"
```

---

### Task 6: Confirmation infrastructure (nonce + TTL, re-read at execute)

**Files:**
- Modify: `notifier/telegram.py` (add a pending-action store + Yes/No callback handler)
- Test: `tests/test_telegram_confirm.py` (create)

**Interfaces:**
- Produces:
  - `TelegramNotifier._pending: dict[str, dict]` mapping a short nonce → `{"action": str, "args": dict, "expires": float, "label": str}`.
  - `TelegramNotifier._make_confirm(action, args, label) -> tuple[str, InlineKeyboardMarkup]` → confirmation prompt text + Yes/No keyboard (`callback_data="confirm:<nonce>"` / `"cancel:<nonce>"`).
  - `TelegramNotifier._on_confirm(update, context)` — the `CallbackQueryHandler` for `confirm:`/`cancel:`; validates nonce+TTL, re-reads state, dispatches to `_execute_action`, answers the callback.
  - `TelegramNotifier._execute_action(action, args) -> str` — performs `close`/`flatten`/`stop_bot`/`be` against the controller and returns a result string. (Task 7/8 extend the action set; this task implements `close` + `flatten` + `stop_bot`.)
- Consumes: controller `close_position`, `flatten`, `stop_bot`, `move_to_breakeven` (Task 4).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_telegram_confirm.py
import time
import pytest
from unittest.mock import AsyncMock, MagicMock
from notifier.telegram import TelegramNotifier
from notifier.engine_controller import EngineController


def _notifier():
    c = AsyncMock(spec=EngineController)
    c.close_position.return_value = {"status": "closed", "symbol": "BTC/USDT",
                                     "side": "LONG", "residual_qty": 0.0}
    n = TelegramNotifier("t", "1", c)
    return n, c


def _cbquery(data, chat_id="1"):
    q = MagicMock()
    q.data = data
    q.answer = AsyncMock()
    q.edit_message_text = AsyncMock()
    upd = MagicMock()
    upd.callback_query = q
    upd.effective_chat = MagicMock(id=chat_id)
    return upd, q


def test_make_confirm_stores_pending():
    n, _ = _notifier()
    text, markup = n._make_confirm("close", {"symbol": "BTC/USDT", "side": "LONG"},
                                   "Close BTC LONG?")
    assert "Close BTC LONG?" in text
    assert len(n._pending) == 1


@pytest.mark.asyncio
async def test_confirm_executes_and_clears():
    n, c = _notifier()
    _, markup = n._make_confirm("close", {"symbol": "BTC/USDT", "side": "LONG"}, "x")
    nonce = next(iter(n._pending))
    upd, q = _cbquery(f"confirm:{nonce}")
    await n._on_confirm(upd, None)
    c.close_position.assert_awaited_once_with("BTC/USDT", side="LONG", loop_id=None)
    assert nonce not in n._pending
    q.answer.assert_awaited()


@pytest.mark.asyncio
async def test_expired_nonce_is_recoverable():
    n, c = _notifier()
    n._make_confirm("close", {"symbol": "BTC/USDT", "side": "LONG"}, "x")
    nonce = next(iter(n._pending))
    n._pending[nonce]["expires"] = time.monotonic() - 1  # force-expire
    upd, q = _cbquery(f"confirm:{nonce}")
    await n._on_confirm(upd, None)
    c.close_position.assert_not_awaited()
    msg = q.edit_message_text.await_args.args[0] if q.edit_message_text.await_args.args \
        else q.edit_message_text.await_args.kwargs["text"]
    assert "old" in msg.lower() or "expired" in msg.lower()


@pytest.mark.asyncio
async def test_confirm_rejects_unauthorized_chat():
    n, c = _notifier()
    n._make_confirm("close", {"symbol": "BTC/USDT", "side": "LONG"}, "x")
    nonce = next(iter(n._pending))
    upd, q = _cbquery(f"confirm:{nonce}", chat_id="999")
    await n._on_confirm(upd, None)
    c.close_position.assert_not_awaited()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_telegram_confirm.py -v`
Expected: FAIL — `_make_confirm` / `_pending` / `_on_confirm` undefined.

- [ ] **Step 3: Implement the confirmation store + handler**

Add to `TelegramNotifier.__init__`:

```python
        self._pending: dict[str, dict] = {}
        self._confirm_ttl = float(os.getenv("TELEGRAM_CONFIRM_TTL_SECONDS", "120"))
```

Add a small import at the top of `notifier/telegram.py`:

```python
import secrets
import time
```

Add the methods:

```python
    def _make_confirm(self, action: str, args: dict, label: str):
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        nonce = secrets.token_hex(4)
        self._pending[nonce] = {
            "action": action, "args": args, "label": label,
            "expires": time.monotonic() + self._confirm_ttl,
        }
        text = f"{label}\nConfirm?"
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yes", callback_data=f"confirm:{nonce}"),
            InlineKeyboardButton("✖ No", callback_data=f"cancel:{nonce}"),
        ]])
        return text, markup

    def _authorized_callback(self, update) -> bool:
        chat = getattr(update, "effective_chat", None)
        chat_id = getattr(chat, "id", None)
        if chat_id is None:
            return True
        return str(chat_id) == str(self._chat_id)

    async def _on_confirm(self, update, context) -> None:
        query = update.callback_query
        await query.answer()
        if not self._authorized_callback(update):
            await query.edit_message_text("Unauthorized chat.")
            return
        kind, _, nonce = query.data.partition(":")
        pending = self._pending.pop(nonce, None)
        if pending is None or pending["expires"] < time.monotonic():
            await query.edit_message_text(
                "This action is old — /open_positions to act on current positions."
            )
            return
        if kind == "cancel":
            await query.edit_message_text("Cancelled.")
            return
        result = await self._execute_action(pending["action"], pending["args"])
        await query.edit_message_text(result)

    async def _execute_action(self, action: str, args: dict) -> str:
        if action == "close":
            res = await self._controller.close_position(
                args["symbol"], side=args.get("side"), loop_id=args.get("loop_id"))
            return f"{res['symbol']} {res.get('side') or ''}: {res['status']}"
        if action == "be":
            res = await self._controller.move_to_breakeven(
                args["symbol"], side=args.get("side"), loop_id=args.get("loop_id"))
            return f"{res['symbol']} {res.get('side') or ''}: SL→BE {res['status']}"
        if action == "stop_bot":
            await self._controller.stop_bot()
            return "Bot stopped. Open exchange-side protection is unchanged."
        if action == "flatten":
            results = await self._controller.flatten()
            if not results:
                return "Nothing to flatten — no open positions."
            lines = [f"  • {r['symbol']} {r.get('side') or ''}: {r['status']}"
                     for r in results]
            return "Flatten complete:\n" + "\n".join(lines)
        return f"Unknown action: {action}"
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_telegram_confirm.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add notifier/telegram.py tests/test_telegram_confirm.py
git commit -m "feat(telegram): confirmation infra (nonce+TTL, re-read at execute, auth)"
```

---

### Task 7: Inline buttons + callback routing (Close / SL→BE)

**Files:**
- Modify: `notifier/telegram.py` (`cmd_open_positions` attaches buttons; `format_liq_warning` push carries a `[Close]` button; `_on_action` callback routes `close:`/`be:` → confirm; register `CallbackQueryHandler`s in `start()`)
- Test: `tests/test_telegram_buttons.py` (create)

**Interfaces:**
- Produces:
  - `_position_buttons(p: dict) -> InlineKeyboardMarkup` → `[Close] [SL→BE]` with `callback_data="close:<loop>:<symbol>:<side>"` / `"be:<loop>:<symbol>:<side>"` (loop empty string when unknown).
  - `TelegramNotifier._on_action(update, context)` — `CallbackQueryHandler` for `close:`/`be:`; auth-checks, then for `close` builds a confirm (Task 6 `_make_confirm`), for `be` (default-off-gated) dispatches directly via `_execute_action`.
- Consumes: `_make_confirm`/`_execute_action`/`_authorized_callback` (Task 6); controller `move_to_breakeven` (Task 4).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_telegram_buttons.py
import os
import pytest
from unittest.mock import AsyncMock, MagicMock
from notifier.telegram import TelegramNotifier, _position_buttons
from notifier.engine_controller import EngineController


def test_position_buttons_identity_callback_data():
    p = {"symbol": "BTC/USDT", "side": "SHORT", "loop_id": "loop4"}
    markup = _position_buttons(p)
    datas = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert "close:loop4:BTC/USDT:SHORT" in datas
    assert "be:loop4:BTC/USDT:SHORT" in datas


def _cb(data, chat_id="1"):
    q = MagicMock()
    q.data = data
    q.answer = AsyncMock()
    q.edit_message_text = AsyncMock()
    q.message = MagicMock()
    q.message.reply_text = AsyncMock()
    upd = MagicMock()
    upd.callback_query = q
    upd.effective_chat = MagicMock(id=chat_id)
    return upd, q


@pytest.mark.asyncio
async def test_close_button_opens_confirmation():
    c = AsyncMock(spec=EngineController)
    n = TelegramNotifier("t", "1", c)
    upd, q = _cb("close:loop4:BTC/USDT:SHORT")
    await n._on_action(upd, None)
    # a pending confirm was created, no close fired yet
    assert len(n._pending) == 1
    c.close_position.assert_not_awaited()


@pytest.mark.asyncio
async def test_be_button_gated_off_by_default(monkeypatch):
    monkeypatch.delenv("TELEGRAM_ENABLE_BE_BUTTON", raising=False)
    c = AsyncMock(spec=EngineController)
    n = TelegramNotifier("t", "1", c)
    upd, q = _cb("be:loop4:BTC/USDT:SHORT")
    await n._on_action(upd, None)
    c.move_to_breakeven.assert_not_awaited()


@pytest.mark.asyncio
async def test_be_button_runs_when_enabled(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ENABLE_BE_BUTTON", "true")
    c = AsyncMock(spec=EngineController)
    c.move_to_breakeven.return_value = {"status": "moved", "symbol": "BTC/USDT", "side": "SHORT"}
    n = TelegramNotifier("t", "1", c)
    upd, q = _cb("be:loop4:BTC/USDT:SHORT")
    await n._on_action(upd, None)
    c.move_to_breakeven.assert_awaited_once_with("BTC/USDT", side="SHORT", loop_id="loop4")


@pytest.mark.asyncio
async def test_action_rejects_unauthorized_chat():
    c = AsyncMock(spec=EngineController)
    n = TelegramNotifier("t", "1", c)
    upd, q = _cb("close:loop4:BTC/USDT:SHORT", chat_id="999")
    await n._on_action(upd, None)
    assert len(n._pending) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_telegram_buttons.py -v`
Expected: FAIL — `_position_buttons` / `_on_action` undefined.

- [ ] **Step 3: Implement buttons + the action router**

Add module-level helper to `notifier/telegram.py`:

```python
def _position_buttons(p: dict):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    loop = p.get("loop_id") or ""
    ident = f"{loop}:{p['symbol']}:{p.get('side') or ''}"
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Close", callback_data=f"close:{ident}"),
        InlineKeyboardButton("SL→BE", callback_data=f"be:{ident}"),
    ]])
```

Add the router method to `TelegramNotifier`:

```python
    @staticmethod
    def _parse_ident(rest: str) -> dict:
        # rest = "<loop>:<symbol>:<side>"; symbol may contain no ':'
        loop, symbol, side = (rest.split(":", 2) + ["", "", ""])[:3]
        return {"loop_id": loop or None, "symbol": symbol, "side": side or None}

    async def _on_action(self, update, context) -> None:
        query = update.callback_query
        await query.answer()
        if not self._authorized_callback(update):
            await query.edit_message_text("Unauthorized chat.")
            return
        kind, _, rest = query.data.partition(":")
        args = self._parse_ident(rest)
        if kind == "close":
            label = f"Close {args['symbol']} {args['side'] or ''}".strip()
            text, markup = self._make_confirm("close", args, label)
            await query.message.reply_text(text, reply_markup=markup)
            return
        if kind == "be":
            # default-off-gated with the partial-TP feature until a strategy is validated
            if os.getenv("TELEGRAM_ENABLE_BE_BUTTON", "false").lower() not in ("1", "true", "yes"):
                await query.message.reply_text("SL→BE is disabled (set TELEGRAM_ENABLE_BE_BUTTON=true).")
                return
            result = await self._execute_action("be", args)
            await query.message.reply_text(result)
```

In `cmd_open_positions`, attach buttons per position (send one message per futures position so each carries its own identity-keyed buttons; spot positions stay in the single combined text). Replace the send block:

```python
        futures = [p for p in positions if p.get("mode") == "FUTURES"]
        spot = [p for p in positions if p.get("mode") != "FUTURES"]
        if spot:
            await update.message.reply_text("\n".join(
                _format_position_line(p).lstrip("• ").strip() for p in spot
            ))
        for p in futures:
            await update.message.reply_text(
                _format_position_line(p).lstrip("• ").strip(),
                reply_markup=_position_buttons(p),
            )
```

> Note: the widened dicts from Task 1 don't carry `loop_id` per position. For `/open_positions` (legacy/aggregate view) `loop_id` is `None` → callback_data `close::BTC/USDT:LONG`; `_parse_ident` yields `loop_id=None`, and `close_position` matches by symbol+side. That correctly disambiguates the two legs; loop scoping only matters if two loops hold the same symbol+side, which the one-symbol-one-leverage rule already discourages.

Register the handlers in `start()` (after the last `add_handler`, before `await self._app.initialize()`):

```python
        from telegram.ext import CallbackQueryHandler
        self._app.add_handler(CallbackQueryHandler(self._on_confirm, pattern=r"^(confirm|cancel):"))
        self._app.add_handler(CallbackQueryHandler(self._on_action, pattern=r"^(close|be):"))
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_telegram_buttons.py tests/test_telegram_confirm.py tests/test_telegram.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add notifier/telegram.py tests/test_telegram_buttons.py
git commit -m "feat(telegram): inline Close/SL→BE buttons with identity callbacks (BE gated)"
```

---

### Task 8: `/flatten` panic command + `/close` confirmation

**Files:**
- Modify: `notifier/telegram.py` (`cmd_flatten` new; `cmd_close` routes through confirm + identity; register `/flatten` in `start()` + `cmd_help`)
- Test: `tests/test_telegram_flatten.py` (create)

**Interfaces:**
- Consumes: `_make_confirm`/`_execute_action` (Task 6), controller `flatten`/`close_position` (Task 4), `get_status` open_positions (Task 1).
- Produces: `cmd_flatten(update, context)` and an updated `cmd_close(update, context)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_telegram_flatten.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from notifier.telegram import TelegramNotifier
from notifier.engine_controller import EngineController


def _msg(args=None, chat_id="1"):
    upd = MagicMock()
    upd.effective_chat = MagicMock(id=chat_id)
    upd.message = MagicMock()
    upd.message.reply_text = AsyncMock()
    ctx = MagicMock()
    ctx.args = args or []
    return upd, ctx


@pytest.mark.asyncio
async def test_flatten_confirms_scope_before_acting():
    c = AsyncMock(spec=EngineController)
    c.get_status.return_value = {"open_positions": [
        {"symbol": "BTC/USDT", "side": "LONG", "mode": "FUTURES"},
        {"symbol": "ETH/USDT", "side": "SHORT", "mode": "FUTURES"},
    ]}
    n = TelegramNotifier("t", "1", c)
    upd, ctx = _msg()
    await n.cmd_flatten(upd, ctx)
    # confirmation prompt mentioning the count; no flatten yet
    c.flatten.assert_not_awaited()
    sent = upd.message.reply_text.await_args
    text = sent.args[0] if sent.args else sent.kwargs["text"]
    assert "2" in text  # scope count surfaced
    assert len(n._pending) == 1


@pytest.mark.asyncio
async def test_flatten_rejects_unauthorized():
    c = AsyncMock(spec=EngineController)
    n = TelegramNotifier("t", "1", c)
    upd, ctx = _msg(chat_id="999")
    await n.cmd_flatten(upd, ctx)
    c.get_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_close_requires_side_when_arg_given():
    c = AsyncMock(spec=EngineController)
    n = TelegramNotifier("t", "1", c)
    upd, ctx = _msg(args=["BTC", "SHORT"])
    await n.cmd_close(upd, ctx)
    # opens a confirmation rather than closing directly
    assert len(n._pending) == 1
    c.close_position.assert_not_awaited()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_telegram_flatten.py -v`
Expected: FAIL — `cmd_flatten` undefined; old `cmd_close` closes directly.

- [ ] **Step 3: Implement `/flatten` and route `/close` through confirm**

Add to `TelegramNotifier`:

```python
    async def cmd_flatten(self, update, context) -> None:
        if await self._reject_if_unauthorized(update):
            return
        status = await self._controller.get_status()
        positions = status.get("open_positions") or []
        n = len(positions)
        if n == 0:
            await update.message.reply_text("No open positions — nothing to flatten.")
            return
        text, markup = self._make_confirm(
            "flatten", {}, f"⚠️ Close ALL {n} position(s) across all loops?")
        await update.message.reply_text(text, reply_markup=markup)
```

Replace `cmd_close`:

```python
    async def cmd_close(self, update, context) -> None:
        if await self._reject_if_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /close <symbol> [LONG|SHORT]  e.g. /close BTC SHORT")
            return
        symbol = context.args[0].upper()
        side = context.args[1].upper() if len(context.args) > 1 else None
        if side not in (None, "LONG", "SHORT"):
            await update.message.reply_text("Side must be LONG or SHORT.")
            return
        args = {"symbol": symbol, "side": side, "loop_id": None}
        label = f"Close {symbol} {side or ''}".strip()
        text, markup = self._make_confirm("close", args, label)
        await update.message.reply_text(text, reply_markup=markup)
```

> Note: `close_position` matches `p.symbol == symbol or p.symbol.startswith(symbol)`, so `/close BTC` still resolves `BTC/USDT`. When a symbol holds both legs and no side is given, the controller closes every matching leg — surface that in `_execute_action`'s summary (it already returns per-result status).

Register `/flatten` in `start()` (with the other `add_handler` calls):

```python
        self._app.add_handler(CommandHandler("flatten", self.cmd_flatten))
```

Add `/flatten` to `cmd_help` text.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_telegram_flatten.py tests/test_telegram.py -v`
Expected: PASS. (Update `test_handle_close_command` in `tests/test_telegram.py` to expect a confirmation prompt now, not an immediate close.)

- [ ] **Step 5: Commit**

```bash
git add notifier/telegram.py tests/test_telegram_flatten.py tests/test_telegram.py
git commit -m "feat(telegram): /flatten panic + /close confirmation (identity-aware)"
```

---

### Task 9: Native autocomplete + drawdown headroom + notification loudness

**Files:**
- Modify: `notifier/telegram.py` (`set_my_commands` in `start()`; `format_risk_status` drawdown headroom; `send_daily_summary`/`send_weekly_summary` quiet flag)
- Modify: `core/live_controller.py` (`get_risk_status` includes `current_drawdown_pct` if available)
- Test: `tests/test_telegram_polish.py` (create)

**Interfaces:**
- Consumes: `get_risk_status()` dict (Task adds `current_drawdown_pct`, `max_drawdown_limit_pct` already present).
- Produces: `format_risk_status` renders a `Drawdown headroom` line; `send()` accepts `quiet: bool=False` → `disable_notification`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_telegram_polish.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from notifier.telegram import format_risk_status, TelegramNotifier
from notifier.engine_controller import EngineController


def test_risk_status_shows_drawdown_headroom():
    status = {"available": True, "global_kill_switch": False, "circuit_breaker": False,
              "daily_loss_limit_pct": 0.03, "max_drawdown_limit_pct": 0.10,
              "max_exposure_pct": 0.5, "current_drawdown_pct": 0.04}
    text = format_risk_status(status)
    # headroom = 0.10 - 0.04 = 6%
    assert "headroom" in text.lower()
    assert "6%" in text


def test_risk_status_headroom_absent_when_no_drawdown_data():
    status = {"available": True, "max_drawdown_limit_pct": 0.10}
    text = format_risk_status(status)  # current_drawdown_pct missing → no crash
    assert "Risk Status" in text


@pytest.mark.asyncio
async def test_send_quiet_sets_disable_notification():
    n = TelegramNotifier("t", "1", AsyncMock(spec=EngineController))
    n._app = MagicMock()
    n._app.bot.send_message = AsyncMock()
    await n.send("hi", quiet=True)
    kwargs = n._app.bot.send_message.await_args.kwargs
    assert kwargs.get("disable_notification") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_telegram_polish.py -v`
Expected: FAIL — no headroom line; `send()` has no `quiet` param.

- [ ] **Step 3: Implement headroom, quiet send, and autocomplete**

In `format_risk_status`, after the `Max drawdown` line, add a headroom line when the data is present. Change the `lines` construction to append conditionally (after the existing list is built, before the kill-switch reasons):

```python
    current_dd = status.get("current_drawdown_pct")
    max_dd = status.get("max_drawdown_limit_pct")
    if current_dd is not None and max_dd is not None:
        headroom = max_dd - current_dd
        lines.append(f"Drawdown headroom: {headroom:.0%} (of {max_dd:.0%} max)")
```

Update `send` to accept `quiet`:

```python
    async def send(self, text: str, *, quiet: bool = False) -> None:
        if self._app is None:
            logger.warning("TelegramNotifier.send() called but bot not started — message dropped")
            return
        await self._app.bot.send_message(
            chat_id=self._chat_id, text=text, disable_notification=quiet)
```

Make the routine summaries quiet — in `send_daily_summary` and `send_weekly_summary`, change `await self.send(text)` / `await self.send(format_weekly_summary(trades))` to pass `quiet=True`. (Liq warnings and order/close confirmations stay loud.)

In `start()`, after `await self._app.start()`, register the trimmed native command list:

```python
        from telegram import BotCommand
        await self._app.bot.set_my_commands([
            BotCommand("status", "Bot + positions status"),
            BotCommand("pnl", "Profit & loss"),
            BotCommand("open_positions", "Open positions"),
            BotCommand("close", "Close a position (symbol [LONG|SHORT])"),
            BotCommand("flatten", "Close ALL positions (panic)"),
            BotCommand("pause", "Pause new orders"),
            BotCommand("resume", "Resume trading"),
            BotCommand("help", "List commands"),
        ])
```

In `core/live_controller.py` `get_risk_status`, enrich with current drawdown if the risk manager exposes it:

```python
    async def get_risk_status(self) -> dict:
        if self._risk_manager is None:
            return {"available": False}
        status = self._risk_manager.status()
        status["available"] = True
        if "current_drawdown_pct" not in status and hasattr(self._risk_manager, "current_drawdown_pct"):
            status["current_drawdown_pct"] = self._risk_manager.current_drawdown_pct()
        return status
```

> Note: if `RiskManager` has no `current_drawdown_pct()` method, leave the key absent — the formatter already no-ops when it's missing (second test). Do not invent a drawdown calc here; that's a risk-formula change out of scope for a UX task.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_telegram_polish.py tests/test_telegram.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add notifier/telegram.py core/live_controller.py tests/test_telegram_polish.py
git commit -m "feat(telegram): native autocomplete (8 cmds) + drawdown headroom + quiet summaries"
```

---

## Final whole-branch review

After Task 9, run the full suite (`.venv/bin/python -m pytest -q` — expect green, ≥527 + new tests) and dispatch a final whole-branch code review (Opus on the close/liq-warning safety paths). Triage any Minor findings, then use `superpowers:finishing-a-development-branch`.

**Cross-task seams the final review must check:**
- Spot output byte-for-byte unchanged (golden assertions in Tasks 2/3 plus the pre-existing `tests/test_telegram*.py`).
- `close_position` ABC signature change: every `EngineController` subclass implements the new `close_position`/`flatten`/`move_to_breakeven` (search the repo; `api/main.py` uses an ad-hoc non-subclass controller and does not call them).
- No import cycle from `core/trading_loop.py` → `core/live_controller.py`.
- Liq-warning fires from the real poll with the same `_position_dict` the commands use; futures-only; hard tier repeats, soft re-arms.
- All callbacks + new commands enforce auth; destructive actions go through confirm with nonce+TTL; expired taps are recoverable.
- `LIVE_TRADING_ENABLED` still false; no real-money path armed.
