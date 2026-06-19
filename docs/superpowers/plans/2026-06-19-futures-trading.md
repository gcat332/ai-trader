# Futures Trading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add USDT-M perpetual futures (long + short, leverage, isolated margin) to the bot, gated paper → testnet → mainnet, without disturbing existing spot/long-only loops.

**Architecture:** Keep the `exchange/base.py::Exchange` ABC as the seam; add a `PaperFuturesExchange` (and later `BinanceFuturesExchange`) implementing it. Make `core/engine.py` and `risk/manager.py` market-aware: in futures `BUY`=open long, `SELL`=open short, exits are `reduce_only`, opposite signal is close-only. Per-loop `market`/`leverage` config selects the exchange and is threaded into the shared `RiskManager.evaluate` as call arguments (the singleton keeps its global daily-loss/drawdown state).

**Tech Stack:** Python 3.12, asyncio, ccxt (async), pandas, pytest, aiosqlite, dataclasses.

## Global Constraints

- USDT-M **linear** futures only; **isolated** margin; **one-way** position mode. No hedge mode, no cross margin, no COIN-M.
- Futures `BUY` = open/add long; `SELL` = open short. Spot semantics unchanged (`SELL` = exit long).
- Opposite signal = **close-only** (reduce_only). No auto-flip; reverse entry must re-pass the full risk gate.
- The single shared `RiskManager` keeps global state (daily-loss, drawdown, kill switches). Per-loop market/leverage/risk params are passed **into** `evaluate(...)`, never stored on the singleton.
- Hard risk gates (from spec §8): `MAX_DRAWDOWN_LIMIT_PCT=0.10`, `DAILY_LOSS_LIMIT_PCT=0.03`. A futures entry whose stop-loss sits beyond the liquidation price is rejected (`liquidation_too_close`).
- Maintenance-margin rate default `mmr=0.005`; recommended leverage 3–5x (config, not enforced in code).
- TDD: failing test first, frequent commits. Match existing code style (no docstring-heavy classes; `# ponytail:` comments name simplification ceilings).
- All money math in `core/models.py` dataclasses; floats rounded to 8dp for quantities like existing code.

---

## Scope of THIS plan

This plan delivers **Milestone M1 (paper futures + core risk)** and **§9 strategy-selection** in full, executable detail — the two workstreams with **zero dependency on unbuilt code**. M1 is the foundation and the validation gate for everything else.

**M2 (testnet), M3 (mainnet), §10 (ML), §11 (Telegram UX)** get their own plans authored when their upstream interfaces are real — writing detailed TDD steps for them now would invent signatures that M1 defines and skip the validation gates the spec mandates. Their task outlines are in the "Follow-on plans" section at the end so the whole shape is visible.

---

# PART A — Milestone M1: Paper Futures + Core Risk

## File Structure (M1)

- `core/models.py` — MODIFY: add `Order.reduce_only`, `Position.leverage`, `Position.liquidation_price`.
- `core/strategy_runtime.py` — MODIFY: add `market`, `leverage`, `risk_per_trade`, `max_hold_hours`, `reentry_cooldown_bars` to `StrategyRuntimeConfig`.
- `core/loop_config.py` — MODIFY: parse the new per-loop env keys with global/default fallback.
- `exchange/futures_math.py` — CREATE: pure functions for liquidation price + PnL (no I/O, trivially testable, shared by paper + later live).
- `exchange/paper_futures.py` — CREATE: `PaperFuturesExchange(Exchange)`.
- `risk/manager.py` — MODIFY: `evaluate(...)` gains market/leverage/risk params, short-side validation, margin sizing, liquidation guard.
- `core/engine.py` — MODIFY: market-aware signal handling, reduce_only exits, short trailing, time-stop, reentry cooldown.
- `main.py` — MODIFY: in paper mode, build `PaperFuturesExchange` for loops with `market=futures`.
- Tests: `tests/test_futures_math.py`, `tests/test_paper_futures.py`, `tests/test_risk_manager.py` (extend), `tests/test_engine.py` (extend), `tests/test_loop_config.py` (extend).

---

### Task 1: Models — futures fields

**Files:**
- Modify: `core/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `Order.reduce_only: bool = False`; `Position.leverage: int = 1`; `Position.liquidation_price: float | None = None`. All defaulted so existing spot construction is unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py  (add)
from core.models import Order, Position

def test_order_reduce_only_defaults_false():
    o = Order(id="1", symbol="BTC/USDT", side="SELL", type="MARKET",
              quantity=1.0, price=None, status="PENDING", exchange_order_id=None)
    assert o.reduce_only is False

def test_position_futures_fields_default():
    p = Position(symbol="BTC/USDT", side="SHORT", entry_price=100.0, quantity=1.0,
                 unrealized_pnl=0.0, take_profit=None, stop_loss=None, mode="FUTURES")
    assert p.leverage == 1
    assert p.liquidation_price is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -k "reduce_only or futures_fields" -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword` is not hit (fields absent), `AttributeError: 'Order' object has no attribute 'reduce_only'`.

- [ ] **Step 3: Write minimal implementation**

In `core/models.py`, add to `Order` (after `strategy_id`):
```python
    reduce_only: bool = False  # futures: marks a closing/reducing order; spot ignores it
```
Add to `Position` (after `strategy_id`):
```python
    leverage: int = 1                       # 1 = spot/no leverage
    liquidation_price: float | None = None  # isolated-margin liq price; None for spot
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -k "reduce_only or futures_fields" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/models.py tests/test_models.py
git commit -m "feat(models): add futures fields (reduce_only, leverage, liquidation_price)"
```

---

### Task 2: Per-loop futures config

**Files:**
- Modify: `core/strategy_runtime.py`, `core/loop_config.py`
- Test: `tests/test_loop_config.py`

**Interfaces:**
- Produces on `StrategyRuntimeConfig`: `market: str = "spot"`, `leverage: int = 1`, `risk_per_trade: float | None = None`, `max_hold_hours: float | None = None`, `reentry_cooldown_bars: int = 0`.
- Env keys (per-loop `LOOPn_` prefix, with the existing `get(KEY, global_default)` fallback pattern): `MARKET`, `LEVERAGE`, `RISK_PER_TRADE`, `MAX_HOLD_HOURS`, `REENTRY_COOLDOWN_BARS`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_loop_config.py  (add)
from core.loop_config import parse_runtime_configs

def test_futures_loop_parsed():
    env = {
        "LOOP1_STRATEGY": "rsi_macd", "LOOP1_MODE": "PAPER",
        "LOOP1_MARKET": "futures", "LOOP1_LEVERAGE": "3",
        "LOOP1_RISK_PER_TRADE": "0.005", "LOOP1_MAX_HOLD_HOURS": "48",
        "LOOP1_REENTRY_COOLDOWN_BARS": "1",
    }
    cfgs = parse_runtime_configs(env)
    cfg = next(c for c in cfgs if c.loop_id != "legacy")
    assert cfg.market == "futures"
    assert cfg.leverage == 3
    assert cfg.risk_per_trade == 0.005
    assert cfg.max_hold_hours == 48.0
    assert cfg.reentry_cooldown_bars == 1

def test_spot_defaults_when_unset():
    env = {"LOOP1_STRATEGY": "rsi_macd", "LOOP1_MODE": "PAPER"}
    cfg = next(c for c in parse_runtime_configs(env) if c.loop_id != "legacy")
    assert cfg.market == "spot"
    assert cfg.leverage == 1
    assert cfg.risk_per_trade is None
    assert cfg.reentry_cooldown_bars == 0

def test_leverage_above_one_requires_futures():
    import pytest
    env = {"LOOP1_STRATEGY": "rsi_macd", "LOOP1_MODE": "PAPER",
           "LOOP1_MARKET": "spot", "LOOP1_LEVERAGE": "3"}
    with pytest.raises(ValueError, match="leverage"):
        parse_runtime_configs(env)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_loop_config.py -k "futures_loop or spot_defaults or leverage_above" -v`
Expected: FAIL — `AttributeError: 'StrategyRuntimeConfig' object has no attribute 'market'`.

- [ ] **Step 3: Write minimal implementation**

In `core/strategy_runtime.py`, add to the `StrategyRuntimeConfig` dataclass (all defaulted, after the existing fields):
```python
    market: str = "spot"                      # "spot" | "futures"
    leverage: int = 1
    risk_per_trade: float | None = None       # fraction of equity risked/trade; None = legacy sizing
    max_hold_hours: float | None = None
    reentry_cooldown_bars: int = 0
```

In `core/loop_config.py`, inside the per-loop build (where `get(KEY, default)` reads other `LOOPn_` values), add:
```python
        market = get("MARKET", env.get("TRADING_MARKET", "spot")).lower()
        leverage = int(get("LEVERAGE", env.get("LEVERAGE", "1")))
        rpt_raw = get("RISK_PER_TRADE", env.get("RISK_PER_TRADE", ""))
        risk_per_trade = float(rpt_raw) if rpt_raw else None
        mhh_raw = get("MAX_HOLD_HOURS", env.get("MAX_HOLD_HOURS", ""))
        max_hold_hours = float(mhh_raw) if mhh_raw else None
        reentry_cooldown_bars = int(get("REENTRY_COOLDOWN_BARS", env.get("REENTRY_COOLDOWN_BARS", "0")))
        if market not in ("spot", "futures"):
            raise ValueError(f"{prefix}MARKET={market!r}; expected spot|futures")
        if leverage > 1 and market != "futures":
            raise ValueError(f"{prefix}LEVERAGE={leverage} requires MARKET=futures")
```
Pass these into the `StrategyRuntimeConfig(...)` constructor call. Apply the same defaults in the `legacy` config branch (market="spot", leverage=1, etc. — defaults already cover it, so the legacy `StrategyRuntimeConfig(...)` needs no change).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_loop_config.py -k "futures_loop or spot_defaults or leverage_above" -v`
Expected: PASS

- [ ] **Step 5: Run the full loop_config suite (no regressions)**

Run: `pytest tests/test_loop_config.py -v`
Expected: PASS (all)

- [ ] **Step 6: Commit**

```bash
git add core/strategy_runtime.py core/loop_config.py tests/test_loop_config.py
git commit -m "feat(config): per-loop futures market/leverage/risk settings"
```

---

### Task 3: Futures math (liquidation price + PnL)

**Files:**
- Create: `exchange/futures_math.py`
- Test: `tests/test_futures_math.py`

**Interfaces:**
- Produces:
  - `liquidation_price(side: str, entry: float, leverage: int, mmr: float = 0.005) -> float`
  - `realized_pnl(side: str, entry: float, exit: float, quantity: float) -> float`
  - Pure functions, no I/O. `side` is `"LONG"`/`"SHORT"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_futures_math.py
from exchange.futures_math import liquidation_price, realized_pnl

def test_long_liquidation_below_entry():
    # 5x long at 100, mmr 0: liq ~ 100*(1 - 1/5) = 80
    assert liquidation_price("LONG", 100.0, 5, mmr=0.0) == 80.0

def test_short_liquidation_above_entry():
    # 5x short at 100, mmr 0: liq ~ 100*(1 + 1/5) = 120
    assert liquidation_price("SHORT", 100.0, 5, mmr=0.0) == 120.0

def test_mmr_widens_long_liquidation_upward():
    # mmr makes liq closer to entry (hit sooner) for longs -> higher than the mmr=0 case
    assert liquidation_price("LONG", 100.0, 5, mmr=0.005) > 80.0

def test_pnl_long_and_short_signs():
    assert realized_pnl("LONG", 100.0, 110.0, 2.0) == 20.0
    assert realized_pnl("SHORT", 100.0, 110.0, 2.0) == -20.0
    assert realized_pnl("SHORT", 100.0, 90.0, 2.0) == 20.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_futures_math.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'exchange.futures_math'`.

- [ ] **Step 3: Write minimal implementation**

```python
# exchange/futures_math.py
"""Pure isolated-margin, one-way futures math. No I/O.
# ponytail: simplified — ignores Binance tiered maintenance margin and funding.
# Upgrade to the tier table if paper/live liquidation prices diverge materially."""


def liquidation_price(side: str, entry: float, leverage: int, mmr: float = 0.005) -> float:
    # Isolated one-way approximation. Long liquidates as price falls, short as it rises.
    if leverage <= 0:
        raise ValueError("leverage must be >= 1")
    if side.upper() == "LONG":
        return entry * (1 - 1 / leverage + mmr)
    return entry * (1 + 1 / leverage - mmr)


def realized_pnl(side: str, entry: float, exit: float, quantity: float) -> float:
    direction = 1.0 if side.upper() == "LONG" else -1.0
    return direction * (exit - entry) * quantity
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_futures_math.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add exchange/futures_math.py tests/test_futures_math.py
git commit -m "feat(exchange): isolated-margin futures math (liquidation, pnl)"
```

---

### Task 4: PaperFuturesExchange — open long/short with margin + slippage

**Files:**
- Create: `exchange/paper_futures.py`
- Test: `tests/test_paper_futures.py`

**Interfaces:**
- Consumes: `Exchange` ABC (`exchange/base.py`), `core.models.{Order,Position}`, `exchange.futures_math.{liquidation_price,realized_pnl}`.
- Produces: `PaperFuturesExchange(initial_balance: dict[str, float], leverage: int = 1, slippage_bps: float = 1.0, mmr: float = 0.005, fee_rate: float = 0.0004)`. Methods: `place_order`, `protect_position`, `cancel_order`, `get_positions`, `get_balance`, `tick(symbol, high, low, close)`, `fetch_ohlcv` (raises NotImplementedError — paper feeds candles externally, mirror `PaperExchange`).
- Positions keyed by `(symbol, strategy_id)`. Opening reserves margin `notional/leverage` from USDT; rejects if insufficient. Entry fills apply slippage on the worse side.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_paper_futures.py
import pytest
from core.models import Order
from exchange.paper_futures import PaperFuturesExchange


def _order(side, qty, sid="s1"):
    return Order(id="o-"+side, symbol="BTC/USDT", side=side, type="MARKET",
                 quantity=qty, price=None, status="PENDING", exchange_order_id=None,
                 strategy_id=sid)


@pytest.mark.asyncio
async def test_open_long_reserves_margin():
    ex = PaperFuturesExchange({"USDT": 1000.0}, leverage=5, slippage_bps=0.0)
    await ex.place_order(_order("BUY", 1.0), current_price=100.0)
    bal = await ex.get_balance()
    # notional 100, 5x -> 20 margin reserved
    assert bal["USDT"] == pytest.approx(980.0, abs=0.01)
    pos = (await ex.get_positions())[0]
    assert pos.side == "LONG"
    assert pos.leverage == 5
    assert pos.liquidation_price is not None and pos.liquidation_price < 100.0


@pytest.mark.asyncio
async def test_open_short_creates_short_position():
    ex = PaperFuturesExchange({"USDT": 1000.0}, leverage=2, slippage_bps=0.0)
    await ex.place_order(_order("SELL", 1.0), current_price=100.0)
    pos = (await ex.get_positions())[0]
    assert pos.side == "SHORT"
    assert pos.liquidation_price > 100.0


@pytest.mark.asyncio
async def test_entry_slippage_worsens_fill():
    ex = PaperFuturesExchange({"USDT": 1000.0}, leverage=1, slippage_bps=10.0)  # 0.1%
    await ex.place_order(_order("BUY", 1.0), current_price=100.0)
    pos = (await ex.get_positions())[0]
    assert pos.entry_price == pytest.approx(100.1, abs=0.001)  # long pays up


@pytest.mark.asyncio
async def test_open_rejects_insufficient_margin():
    ex = PaperFuturesExchange({"USDT": 10.0}, leverage=1, slippage_bps=0.0)
    with pytest.raises(ValueError, match="margin"):
        await ex.place_order(_order("BUY", 1.0), current_price=100.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_paper_futures.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'exchange.paper_futures'`.

- [ ] **Step 3: Write minimal implementation**

```python
# exchange/paper_futures.py
import uuid
from core.models import Order, Position, TradeRecord
from exchange.base import Exchange
from exchange.futures_math import liquidation_price, realized_pnl


class PaperFuturesExchange(Exchange):
    """In-memory USDT-M futures sim: long/short, isolated margin, leverage,
    slippage, liquidation. Candles are fed via tick(); no network."""

    def __init__(self, initial_balance: dict[str, float], leverage: int = 1,
                 slippage_bps: float = 1.0, mmr: float = 0.005, fee_rate: float = 0.0004):
        self._balance = dict(initial_balance)
        self._leverage = leverage
        self._slippage = slippage_bps / 10000.0
        self._mmr = mmr
        self._fee_rate = fee_rate
        # (symbol, strategy_id) -> Position (with extra margin bookkeeping on the object)
        self._positions: dict[tuple[str, str], Position] = {}
        self._margin: dict[tuple[str, str], float] = {}
        self.closed_trades: list[TradeRecord] = []

    async def fetch_ohlcv(self, symbol, timeframe, limit):
        raise NotImplementedError("PaperFuturesExchange is fed candles via tick()")

    def _fill_price(self, side: str, price: float) -> float:
        # Worse side: buys pay up, sells get less.
        return price * (1 + self._slippage) if side == "BUY" else price * (1 - self._slippage)

    async def place_order(self, order: Order, current_price: float = 0.0,
                          stop_price: float | None = None) -> Order:
        filled = Order(**order.__dict__)
        key = (order.symbol, order.strategy_id)
        if order.reduce_only:
            return await self._close(order, current_price, filled)
        side = "LONG" if order.side == "BUY" else "SHORT"
        fill = self._fill_price(order.side, current_price)
        notional = fill * order.quantity
        margin = notional / self._leverage
        usdt = self._balance.get("USDT", 0.0)
        if margin > usdt:
            raise ValueError(f"insufficient margin: need {margin:.2f}, have {usdt:.2f}")
        self._balance["USDT"] = usdt - margin - notional * self._fee_rate
        self._positions[key] = Position(
            symbol=order.symbol, side=side, entry_price=fill, quantity=order.quantity,
            unrealized_pnl=0.0, take_profit=None, stop_loss=None, mode="FUTURES",
            strategy_id=order.strategy_id, leverage=self._leverage,
            liquidation_price=liquidation_price(side, fill, self._leverage, self._mmr),
        )
        self._margin[key] = margin
        filled.exchange_order_id = str(uuid.uuid4())
        filled.status = "FILLED"
        return filled

    async def _close(self, order, current_price, filled):
        key = (order.symbol, order.strategy_id)
        pos = self._positions.get(key)
        if pos is None:
            filled.status = "FAILED"
            return filled
        fill = self._fill_price(order.side, current_price)
        self._realize(key, pos, fill, "MANUAL")
        filled.exchange_order_id = str(uuid.uuid4())
        filled.status = "FILLED"
        return filled

    def _realize(self, key, pos, exit_price, reason):
        from datetime import datetime, timezone
        pnl = realized_pnl(pos.side, pos.entry_price, exit_price, pos.quantity)
        notional = exit_price * pos.quantity
        self._balance["USDT"] = (self._balance.get("USDT", 0.0)
                                 + self._margin.pop(key, 0.0) + pnl
                                 - notional * self._fee_rate)
        self.closed_trades.append(TradeRecord(
            symbol=pos.symbol, side="SELL" if pos.side == "LONG" else "BUY",
            entry_price=pos.entry_price, exit_price=exit_price, quantity=pos.quantity,
            realized_pnl=pnl, entry_time=datetime.now(timezone.utc),
            exit_time=datetime.now(timezone.utc), exit_reason=reason,
            strategy_id=pos.strategy_id,
        ))
        del self._positions[key]

    async def protect_position(self, symbol, side, quantity, take_profit, stop_loss,
                               current_price=0.0, strategy_id=""):
        pos = self._positions.get((symbol, strategy_id))
        if pos is not None:
            pos.take_profit = take_profit
            pos.stop_loss = stop_loss
        return None  # paper enforces TP/SL in tick(), like PaperExchange

    async def cancel_order(self, order_id, symbol):
        return None

    async def get_positions(self):
        return list(self._positions.values())

    async def get_balance(self):
        return {k: v for k, v in self._balance.items() if v > 0}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_paper_futures.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add exchange/paper_futures.py tests/test_paper_futures.py
git commit -m "feat(exchange): PaperFuturesExchange open long/short with margin+slippage"
```

---

### Task 5: PaperFuturesExchange — tick() TP/SL/liquidation + close PnL

**Files:**
- Modify: `exchange/paper_futures.py`
- Test: `tests/test_paper_futures.py`

**Interfaces:**
- Produces: `tick(symbol, high, low, close) -> list[TradeRecord]` — for each position on `symbol`, check **liquidation first** (worst case), then SL, then TP; close on hit and append a `TradeRecord`. `reduce_only` close PnL already wired in Task 4 (`_close`/`_realize`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_paper_futures.py  (add)
@pytest.mark.asyncio
async def test_long_take_profit_hit_positive_pnl():
    ex = PaperFuturesExchange({"USDT": 1000.0}, leverage=2, slippage_bps=0.0)
    await ex.place_order(_order("BUY", 1.0), current_price=100.0)
    await ex.protect_position("BTC/USDT", "BUY", 1.0, take_profit=110.0,
                              stop_loss=95.0, strategy_id="s1")
    closed = ex.tick("BTC/USDT", high=111.0, low=109.0, close=110.0)
    assert len(closed) == 1 and closed[0].exit_reason == "TP"
    assert closed[0].realized_pnl == pytest.approx(10.0, abs=0.01)
    assert (await ex.get_positions()) == []

@pytest.mark.asyncio
async def test_short_stop_loss_hit_negative_pnl():
    ex = PaperFuturesExchange({"USDT": 1000.0}, leverage=2, slippage_bps=0.0)
    await ex.place_order(_order("SELL", 1.0), current_price=100.0)
    await ex.protect_position("BTC/USDT", "SELL", 1.0, take_profit=90.0,
                              stop_loss=105.0, strategy_id="s1")
    closed = ex.tick("BTC/USDT", high=106.0, low=104.0, close=105.0)
    assert closed[0].exit_reason == "SL"
    assert closed[0].realized_pnl == pytest.approx(-5.0, abs=0.01)

@pytest.mark.asyncio
async def test_liquidation_takes_precedence():
    # 2x long at 100 -> liq ~ 100*(1-0.5+0.005)=50.5. A wick to 50 liquidates
    # even though SL=60 would also be crossed; liquidation must win.
    ex = PaperFuturesExchange({"USDT": 1000.0}, leverage=2, slippage_bps=0.0)
    await ex.place_order(_order("BUY", 1.0), current_price=100.0)
    await ex.protect_position("BTC/USDT", "BUY", 1.0, take_profit=130.0,
                              stop_loss=60.0, strategy_id="s1")
    closed = ex.tick("BTC/USDT", high=70.0, low=50.0, close=55.0)
    assert closed[0].exit_reason == "LIQUIDATION"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_paper_futures.py -k "take_profit or stop_loss or liquidation_takes" -v`
Expected: FAIL — `AttributeError: 'PaperFuturesExchange' object has no attribute 'tick'`.

- [ ] **Step 3: Write minimal implementation**

Add `"LIQUIDATION"` to the `TradeRecord.exit_reason` Literal in `core/models.py`:
```python
    exit_reason: Literal["TP", "SL", "MANUAL", "LIQUIDATION"]
```
Add `tick` to `PaperFuturesExchange`:
```python
    def tick(self, symbol, high, low, close):
        closed = []
        for key, pos in list(self._positions.items()):
            exit_price = reason = None
            liq = pos.liquidation_price
            if pos.side == "LONG":
                if liq is not None and low <= liq:
                    exit_price, reason = liq, "LIQUIDATION"
                elif pos.stop_loss is not None and low <= pos.stop_loss:
                    exit_price, reason = pos.stop_loss, "SL"
                elif pos.take_profit is not None and high >= pos.take_profit:
                    exit_price, reason = pos.take_profit, "TP"
            else:  # SHORT
                if liq is not None and high >= liq:
                    exit_price, reason = liq, "LIQUIDATION"
                elif pos.stop_loss is not None and high >= pos.stop_loss:
                    exit_price, reason = pos.stop_loss, "SL"
                elif pos.take_profit is not None and low <= pos.take_profit:
                    exit_price, reason = pos.take_profit, "TP"
            if reason:
                self._realize(key, pos, exit_price, reason)
                closed.append(self.closed_trades[-1])
        return closed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_paper_futures.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add exchange/paper_futures.py core/models.py tests/test_paper_futures.py
git commit -m "feat(exchange): PaperFuturesExchange tick TP/SL/liquidation precedence"
```

---

### Task 6: RiskManager — market/leverage/risk-aware evaluate

**Files:**
- Modify: `risk/manager.py`
- Test: `tests/test_risk_manager.py`

**Interfaces:**
- Consumes: existing `evaluate(self, signal, balance, positions)`.
- Produces: `evaluate(self, signal, balance, positions, *, market="spot", leverage=1, risk_per_trade=None, mmr=0.005, liq_buffer_pct=0.0)`.
  - Futures: `SELL` is allowed to open a short (no `sell_no_position` reject); short stop validated `stop_loss > entry_price`; sizing uses `risk_per_trade` off stop distance when set, capped by margin; **liquidation guard** rejects (`liquidation_too_close`) when SL is at/beyond the liq price. The returned `Order.reduce_only` stays `False` for entries (engine sets it for exits).
  - Spot path: **unchanged** behavior (defaults reproduce today's logic).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_risk_manager.py  (add)
from datetime import datetime, timezone
from core.models import Signal, Position
from risk.manager import RiskManager

def _sig(side, sl, entry=100.0, conf=0.9):
    return Signal(symbol="BTC/USDT", side=side, entry_price=entry, take_profit=None,
                  stop_loss=sl, trailing_sl=False, confidence=conf, strategy_id="s1",
                  timestamp=datetime.now(timezone.utc))

def test_futures_sell_opens_short_not_rejected():
    rm = RiskManager(confidence_threshold=0.6)
    order = rm.evaluate(_sig("SELL", sl=105.0), {"USDT": 1000.0}, [], market="futures", leverage=2)
    assert order is not None and order.side == "SELL"

def test_futures_short_requires_sl_above_entry():
    rm = RiskManager()
    order = rm.evaluate(_sig("SELL", sl=95.0), {"USDT": 1000.0}, [], market="futures", leverage=2)
    assert order is None
    assert rm.last_rejection_reason == "short_stop_below_entry"

def test_risk_per_trade_sizes_off_stop_distance():
    rm = RiskManager()
    # risk 1% of 1000 = 10 USDT; stop distance 100-95 = 5 -> qty 2.0
    order = rm.evaluate(_sig("BUY", sl=95.0), {"USDT": 1000.0}, [],
                        market="futures", leverage=5, risk_per_trade=0.01)
    assert order.quantity == 2.0

def test_liquidation_guard_rejects_sl_beyond_liq():
    rm = RiskManager()
    # 20x long at 100 -> liq ~ 95.5; an SL at 94 is beyond liq -> reject
    order = rm.evaluate(_sig("BUY", sl=94.0), {"USDT": 1000.0}, [],
                        market="futures", leverage=20, risk_per_trade=0.01)
    assert order is None
    assert rm.last_rejection_reason == "liquidation_too_close"

def test_spot_unchanged_sell_without_position_rejected():
    rm = RiskManager()
    order = rm.evaluate(_sig("SELL", sl=95.0), {"USDT": 1000.0}, [])  # market defaults spot
    assert order is None and rm.last_rejection_reason == "sell_no_position"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_risk_manager.py -k "futures or risk_per_trade or liquidation_guard or spot_unchanged" -v`
Expected: FAIL — `TypeError: evaluate() got an unexpected keyword argument 'market'`.

- [ ] **Step 3: Write minimal implementation**

In `risk/manager.py`, import the math and rewrite the direction/sizing portion of `evaluate`:
```python
from exchange.futures_math import liquidation_price
```
Change the signature:
```python
    def evaluate(self, signal, balance, positions, *, market="spot", leverage=1,
                 risk_per_trade=None, mmr=0.005, liq_buffer_pct=0.0) -> Order | None:
```
Keep all global/kill/daily/position-count/confidence gates exactly as they are. Replace the spot-only direction block (the `own_symbols` / `sell_no_position` / `re_entry` / sizing section) with:
```python
        own_symbols = {p.symbol for p in positions if p.strategy_id == signal.strategy_id}
        is_futures = market == "futures"

        if signal.side == "SELL" and not is_futures and signal.symbol not in own_symbols:
            self._last_rejection_reason = "sell_no_position"
            return None
        if signal.side == "BUY" and signal.symbol in own_symbols:
            self._last_rejection_reason = "re_entry"
            return None
        if is_futures and signal.symbol in own_symbols:
            # one-way: a same-symbol re-entry while holding is the engine's cooldown job
            self._last_rejection_reason = "re_entry"
            return None

        _CORRELATED = {"BTC/USDT", "ETH/USDT"}
        opening = signal.side == "BUY" or (is_futures and signal.side == "SELL")
        if opening and signal.symbol in _CORRELATED:
            if any(p.symbol in _CORRELATED and p.symbol != signal.symbol for p in positions):
                self._last_rejection_reason = "correlation_filter"
                return None
        if opening and self._max_exposure_exceeded(balance, positions):
            self._last_rejection_reason = "max_exposure"
            return None

        if signal.confidence < self._confidence_threshold:
            self._last_rejection_reason = "low_confidence"
            return None

        # Direction-aware stop validation + liquidation guard (futures opens only).
        if is_futures and opening:
            if signal.side == "SELL" and not (signal.stop_loss > signal.entry_price):
                self._last_rejection_reason = "short_stop_below_entry"
                return None
            if signal.side == "BUY" and not (signal.stop_loss < signal.entry_price):
                self._last_rejection_reason = "long_stop_above_entry"
                return None
            side_ls = "LONG" if signal.side == "BUY" else "SHORT"
            liq = liquidation_price(side_ls, signal.entry_price, leverage, mmr)
            buffered = liq * (1 - liq_buffer_pct) if side_ls == "LONG" else liq * (1 + liq_buffer_pct)
            sl_beyond = (signal.stop_loss <= buffered) if side_ls == "LONG" else (signal.stop_loss >= buffered)
            if sl_beyond:
                self._last_rejection_reason = "liquidation_too_close"
                return None

        # Sizing.
        if signal.side == "SELL" and not is_futures:
            pos = next((p for p in positions if p.symbol == signal.symbol
                        and p.strategy_id == signal.strategy_id), None)
            quantity = pos.quantity if pos else 0.0
        elif risk_per_trade is not None:
            usdt = balance.get("USDT", 0.0)
            risk_usdt = usdt * risk_per_trade
            stop_distance = abs(signal.entry_price - signal.stop_loss)
            qty = risk_usdt / stop_distance if stop_distance > 0 else 0.0
            # cap by available margin: notional/leverage <= usdt
            max_qty_margin = (usdt * leverage) / signal.entry_price
            quantity = round(min(qty, max_qty_margin), 8)
        else:
            usdt = balance.get("USDT", 0.0)
            scaled_pct = self._max_position_pct * signal.confidence
            quantity = round((usdt * scaled_pct * max(leverage, 1)) / signal.entry_price, 8)

        if quantity <= 0:
            self._last_rejection_reason = "zero_quantity"
            return None

        return Order(
            id=str(uuid.uuid4()), symbol=signal.symbol, side=signal.side, type="MARKET",
            quantity=quantity, price=None, status="PENDING", exchange_order_id=None,
            strategy_id=signal.strategy_id,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_risk_manager.py -v`
Expected: PASS (new + all existing — spot path unchanged)

- [ ] **Step 5: Commit**

```bash
git add risk/manager.py tests/test_risk_manager.py
git commit -m "feat(risk): market/leverage-aware evaluate with liquidation guard"
```

---

### Task 7: Engine — market-aware signal handling

**Files:**
- Modify: `core/engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: `Engine.__init__(...)` (add params), `RiskManager.evaluate(..., market=, leverage=, risk_per_trade=)`, `Order.reduce_only`.
- Produces: `Engine.__init__` gains `market: str = "spot"`, `leverage: int = 1`, `risk_per_trade: float | None = None`, `max_hold_hours: float | None = None`, `reentry_cooldown_bars: int = 0`. Engine passes market/leverage/risk_per_trade into `evaluate`. Futures behavior: `SELL` opens short; opposite-signal closes via a `reduce_only` order; re-entry blocked for `reentry_cooldown_bars` bars after a close; positions older than `max_hold_hours` force-closed.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_engine.py  (add — match the file's existing Engine test fixtures/style)
# Use the existing fake-exchange / strategy helpers in this module. Pseudocode shape:
#
# def make_engine(market="futures", **kw): build Engine with a stub strategy + PaperFuturesExchange
#
# 1. test_futures_sell_signal_opens_short:
#    feed a SELL signal (sl above entry, high conf) -> engine places an order,
#    exchange has a SHORT position.
# 2. test_opposite_signal_closes_only_no_flip:
#    hold a LONG, feed a SELL signal -> engine places a reduce_only close,
#    no new short opened in the same evaluation.
# 3. test_reentry_blocked_during_cooldown:
#    after a close on (symbol, strategy), a same-bar BUY is not opened when
#    reentry_cooldown_bars=1.
# 4. test_time_stop_closes_old_position:
#    a position with entry_time older than max_hold_hours is force-closed on tick.
```
Write these as concrete tests mirroring the existing `tests/test_engine.py` harness (it already constructs `Engine` with a fake exchange + stub strategy; reuse that fixture, swapping in `PaperFuturesExchange` and `market="futures"`). Each asserts on `await exchange.get_positions()` and the placed order's `reduce_only` flag.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_engine.py -k "futures or opposite_signal or cooldown or time_stop" -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'market'`.

- [ ] **Step 3: Write minimal implementation**

In `core/engine.py`:
1. Add the new params to `__init__` and store them (`self._market`, `self._leverage`, `self._risk_per_trade`, `self._max_hold_hours`, `self._reentry_cooldown_bars`). Add cooldown + open-time bookkeeping: `self._cooldown: dict[tuple[str, str], int] = {}` and rely on the exchange Position for entry time (store `self._opened_at: dict[tuple[str,str], datetime]` on open).
2. Where the engine calls `self._risk_manager.evaluate(signal, balance, positions)`, pass the market params:
```python
order = self._risk_manager.evaluate(
    signal, balance, positions,
    market=self._market, leverage=self._leverage, risk_per_trade=self._risk_per_trade,
)
```
3. Opposite-signal close (futures): before evaluating a fresh entry, if a position exists for `(symbol, strategy_id)` and the signal side is opposite to the held side, place a `reduce_only` market order to close and **return** (do not open the reverse this bar). For spot keep the existing exit behavior.
```python
held = next((p for p in positions if p.symbol == self.symbol
             and p.strategy_id == signal.strategy_id), None)
if self._market == "futures" and held is not None:
    opposite = (held.side == "LONG" and signal.side == "SELL") or \
               (held.side == "SHORT" and signal.side == "BUY")
    if opposite:
        close = Order(id=str(uuid.uuid4()), symbol=self.symbol,
                      side=("SELL" if held.side == "LONG" else "BUY"),
                      type="MARKET", quantity=held.quantity, price=None,
                      status="PENDING", exchange_order_id=None,
                      strategy_id=signal.strategy_id, reduce_only=True)
        await self.exchange.place_order(close, current_price=signal.entry_price)
        self._cooldown[(self.symbol, signal.strategy_id)] = self._reentry_cooldown_bars
        return
```
4. Cooldown: at the top of entry handling, decrement any active cooldown for the key; if `> 0`, skip opening. After a close, set it to `reentry_cooldown_bars`.
5. Time-stop: in the per-bar routine after fetching the latest candle, for each held futures position whose `self._opened_at[key]` is older than `max_hold_hours`, place a `reduce_only` close.

Keep all spot paths and the existing decision-record / trailing logic intact; gate new behavior on `self._market == "futures"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_engine.py -v`
Expected: PASS (new + existing spot tests unchanged)

- [ ] **Step 5: Commit**

```bash
git add core/engine.py tests/test_engine.py
git commit -m "feat(engine): market-aware futures signals, close-only flip, time-stop, cooldown"
```

---

### Task 8: Wire PaperFuturesExchange per loop (paper mode)

**Files:**
- Modify: `main.py`
- Test: `tests/test_go_live_safety.py` (extend) or a new `tests/test_main_wiring.py`

**Interfaces:**
- Consumes: `parse_runtime_configs` (now with `market`/`leverage`), `PaperFuturesExchange`, `Engine` futures params.
- Produces: in paper mode, a loop with `cfg.market == "futures"` gets a `PaperFuturesExchange(initial_balance, leverage=cfg.leverage)` and its `Engine` is built with the futures params. Spot loops keep `PaperExchange`. **Note:** today `main.py` builds ONE shared exchange; this task introduces per-loop exchange selection for paper only (live per-(market,network) isolation is M2).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_main_wiring.py
from types import SimpleNamespace
from main import _build_paper_exchange_for  # helper introduced in step 3

def test_futures_loop_gets_paper_futures_exchange():
    cfg = SimpleNamespace(market="futures", leverage=3)
    ex = _build_paper_exchange_for(cfg, initial_balance={"USDT": 10000.0})
    assert ex.__class__.__name__ == "PaperFuturesExchange"

def test_spot_loop_gets_paper_exchange():
    cfg = SimpleNamespace(market="spot", leverage=1)
    ex = _build_paper_exchange_for(cfg, initial_balance={"USDT": 10000.0})
    assert ex.__class__.__name__ == "PaperExchange"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main_wiring.py -v`
Expected: FAIL — `ImportError: cannot import name '_build_paper_exchange_for'`.

- [ ] **Step 3: Write minimal implementation**

In `main.py`, add a small factory and use it per loop in the paper branch:
```python
from exchange.paper_futures import PaperFuturesExchange

def _build_paper_exchange_for(cfg, initial_balance):
    if getattr(cfg, "market", "spot") == "futures":
        return PaperFuturesExchange(initial_balance, leverage=getattr(cfg, "leverage", 1))
    return PaperExchange(initial_balance=initial_balance)
```
In the loop-spec construction (paper mode), build a per-loop exchange via this factory and store it on the spec (`spec.exchange`), then pass `spec.exchange` (not the single shared `exchange`) into that loop's `Engine`, `run_trading_loop`, reconciliation, and `create_app`. For futures specs, pass the engine futures params:
```python
spec.engine = Engine(
    exchange=spec.exchange, strategy=spec.strategy, symbol=spec.symbol,
    timeframe=spec.timeframe, risk_manager=risk_manager, repo=repo,
    state_path=spec.state_path, allocation_manager=allocation_manager,
    loop_id=spec.config.loop_id, exit_on_opposite_signal=spec.config.exit_on_opposite_signal,
    market=spec.config.market, leverage=spec.config.leverage,
    risk_per_trade=spec.config.risk_per_trade, max_hold_hours=spec.config.max_hold_hours,
    reentry_cooldown_bars=spec.config.reentry_cooldown_bars,
)
```
`# ponytail: paper per-loop exchange only; live per-(market,network) isolation is M2.`
Keep the single-shared-exchange path for spot-only runs working (the factory returns `PaperExchange` so behavior is unchanged when no futures loop exists).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main_wiring.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite (M1 integration gate)**

Run: `pytest -q`
Expected: PASS (whole suite). This is the M1 exit gate alongside a manual paper run.

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_main_wiring.py
git commit -m "feat(main): per-loop PaperFuturesExchange wiring for futures loops"
```

---

## M1 Exit Gate

- `pytest -q` green.
- Manual paper run with a futures loop shows: long opens/closes, short opens/closes, a liquidation event in a forced wick, PnL signs correct, drawdown gate trips at the configured limit. Record the run in `changes.log`.

---

# PART B — §9 Strategy Selection (independent, read-only, runs in parallel)

### Task 9: select_strategy.py — rank rule_based strategies on last 60 days

**Files:**
- Create: `analysis/select_strategy.py`
- Modify: `core/strategy_registry.py` (only if a winning new strategy is added — see Task 10)
- Test: `tests/test_select_strategy.py`

**Interfaces:**
- Consumes: `analysis/run_backtests.py::load_candles` (or its CSV-loading helper), `BacktestRunner`, `BacktestReporter.compute()` (returns `win_rate, total_pnl, max_drawdown, sharpe_ratio, total_trades`).
- Produces: `select_strategy(candles_by_tf, strategies, atr_grid, *, min_trades=30, max_dd=0.10) -> list[dict]` ranked best-first by `sharpe_ratio` after hard filters; writes `analysis/strategy_selection.json`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_select_strategy.py
from analysis.select_strategy import rank_results

def test_rank_filters_and_orders():
    rows = [
        {"strategy": "a", "sharpe_ratio": 2.0, "max_drawdown": 0.05, "total_trades": 40, "total_pnl": 100},
        {"strategy": "b", "sharpe_ratio": 3.0, "max_drawdown": 0.20, "total_trades": 40, "total_pnl": 300},  # dd>10% -> drop
        {"strategy": "c", "sharpe_ratio": 2.5, "max_drawdown": 0.04, "total_trades": 10, "total_pnl": 50},   # too few -> drop
        {"strategy": "d", "sharpe_ratio": 2.2, "max_drawdown": 0.06, "total_trades": 35, "total_pnl": 120},
    ]
    ranked = rank_results(rows, min_trades=30, max_dd=0.10)
    assert [r["strategy"] for r in ranked] == ["d", "a"]  # d (2.2) then a (2.0); b,c filtered
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_select_strategy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'analysis.select_strategy'`.

- [ ] **Step 3: Write minimal implementation**

```python
# analysis/select_strategy.py
"""Rank rule_based strategies on the last ~60 days by risk-adjusted return.
Reuses the real BacktestRunner/Engine/RiskManager via analysis/run_backtests.py.
# ponytail: long-only backtester today — screens long-side edge; re-run through
# the futures backtester after M1 to validate shorts."""
import json


def rank_results(rows, *, min_trades=30, max_dd=0.10):
    kept = [r for r in rows
            if r["total_trades"] >= min_trades and r["max_drawdown"] <= max_dd]
    return sorted(kept, key=lambda r: (r["sharpe_ratio"], r["total_pnl"]), reverse=True)


ATR_GRID = [(2, 3), (1.5, 3), (2, 4), (1.5, 4), (2.5, 4), (3, 3), (1.5, 2.5)]
RULE_STRATEGIES = ["rsi_macd", "bollinger_reversion", "ema_cross",
                   "trend_pullback", "liquidation_reversion"]


def select_strategy(candles_by_tf, strategies, atr_grid, *, min_trades=30, max_dd=0.10):
    from analysis.run_backtests import run_one  # reuse existing single-backtest runner
    rows = []
    for tf, candles in candles_by_tf.items():
        for name in strategies:
            for sl_mult, tp_mult in atr_grid:
                metrics = run_one(name, candles, sl_mult=sl_mult, tp_mult=tp_mult)
                rows.append({"strategy": name, "timeframe": tf,
                             "atr_sl": sl_mult, "atr_tp": tp_mult, **metrics})
    ranked = rank_results(rows, min_trades=min_trades, max_dd=max_dd)
    with open("analysis/strategy_selection.json", "w") as f:
        json.dump(ranked, f, indent=2)
    return ranked
```
If `analysis/run_backtests.py` has no reusable `run_one`/`load_candles` seam, add a thin one there that wraps the existing `BacktestRunner` + `BacktestReporter.compute()` call (small refactor, no behavior change) and unit-test the slice-last-60-days helper.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_select_strategy.py -v`
Expected: PASS

- [ ] **Step 5: Run the selection on real cached data**

Run: `python -m analysis.select_strategy`  (add an `if __name__ == "__main__"` that loads `analysis/data/BTCUSDT_1h.csv` + `_4h.csv`, slices the last 60 days, calls `select_strategy`).
Expected: prints a ranked table; writes `analysis/strategy_selection.json`.

- [ ] **Step 6: Commit**

```bash
git add analysis/select_strategy.py tests/test_select_strategy.py analysis/strategy_selection.json
git commit -m "feat(analysis): rule_based strategy selection on last 60d (risk-adjusted)"
```

---

### Task 10: Add `supertrend` bidirectional strategy (if it wins the bench)

**Files:**
- Create: `strategy/supertrend.py`
- Modify: `core/strategy_registry.py`
- Test: `tests/test_supertrend.py`

**Interfaces:**
- Consumes: the project's `BaseStrategy` interface + the indicator helpers used by existing strategies (e.g. ATR in `strategy/`).
- Produces: a `supertrend` strategy registered in `core/strategy_registry.py` that emits `BUY` on bullish ATR-band flip and `SELL` on bearish flip (bidirectional — designed for futures).

- [ ] **Step 1–5:** TDD a minimal Supertrend (ATR band flip): test that a synthetic uptrend → `BUY` and a synthetic downtrend → `SELL`; implement using the existing ATR helper; register in the factory/registry next to `rsi_macd`; run `select_strategy` again to confirm it clears the §9.4 filters before adopting. Commit.

> Build this task **only if** §9 (Task 9) shows a bidirectional candidate is needed / `rsi_macd` underperforms on the short side. Otherwise skip (YAGNI) and keep `rsi_macd` as the futures rule. `donchian_breakout` follows the same pattern if pursued; `funding_fade` is deferred to M2 (needs funding data).

---

## Follow-on plans (authored when upstream lands — outlines only)

These are **not** executable yet: they consume interfaces M1 defines and sit behind the spec's validation gates. Each becomes its own dated plan.

- **M2 — Testnet** (`docs/superpowers/plans/<date>-futures-m2-testnet.md`): `BinanceFuturesExchange` (reuses `exchange/futures_math.py` + the `Exchange` ABC + `reduce_only` from M1); `set_leverage`/`set_margin_mode("isolated")`; TP/SL via `TAKE_PROFIT_MARKET`+`STOP_MARKET`; real `fetch_positions` reconciliation; per-(market,network) exchange isolation in `main.py`; **#3 funding-rate awareness** (`fetch_funding_rate`); futures-testnet contract test. **Gate:** contract test green + supervised testnet run. Authored after M1 exit gate passes.
- **M3 — Mainnet + hardening** (`<date>-futures-m3-mainnet.md`): wire futures into `docs/release-safety-validation-gate.md` + `LIVE_TRADING_ENABLED`; **#6 partial-TP/breakeven**; **#7 correlation-aware exposure** (generalize the `{BTC,ETH}` filter); **#8 macro blackout**; mainnet runbook.
- **§10 — ML** (`<date>-ml-optimization.md`): short-side labels in `train_from_history.py`; regime feature (M1-data); futures features funding/OI/L-S-ratio (M2-data); walk-forward validation; LR→LightGBM gated on sample count via `ab_tester`. Rides on M1/M2 data.
- **§11 — Telegram UX** (`<date>-telegram-ux.md`): direction-aware alerts, futures fields in formatters, proactive liquidation warning, inline buttons + `/flatten` panic + drawdown-headroom in `/status` + severity tiers (§11.D). M1-provable parts first; funding alerts in M2.

---

## Self-Review notes

- **Spec coverage (this plan):** §2 decisions → Global Constraints; §5.1 models → Task 1; §5.2 config → Task 2; §5.3 PaperFuturesExchange (margin/slippage/liquidation/tick) → Tasks 3–5; §5.5 risk (short validation/sizing/liq guard/sell=short) → Task 6; §5.4 engine (BUY/SELL semantics, close-only flip, trailing, time-stop, cooldown) → Task 7; per-loop wiring → Task 8; §9 selection → Tasks 9–10. §8 risk config = Global Constraints + verified by M1 exit gate. M2/M3/§10/§11 → follow-on plans (intentionally deferred, with rationale).
- **Placeholders:** Task 7's tests are described against the existing `tests/test_engine.py` harness rather than reproduced verbatim because they must reuse that file's fixtures — the implementer writes them concretely from the four named behaviors. All other code/test steps are concrete.
- **Type consistency:** `evaluate(..., market=, leverage=, risk_per_trade=, mmr=, liq_buffer_pct=)`, `liquidation_price(side, entry, leverage, mmr)`, `realized_pnl(side, entry, exit, quantity)`, `PaperFuturesExchange.tick(symbol, high, low, close)`, `Order.reduce_only`, `Position.leverage/liquidation_price`, `TradeRecord.exit_reason` incl. `"LIQUIDATION"` — used consistently across tasks.
