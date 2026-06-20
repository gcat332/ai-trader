# Futures M3 — Mainnet Enablement + Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make mainnet USDT-M futures safe to arm — go-live gate wiring + one-way enforcement, a mainnet dry-run mode, the M2-deferred hardening, and risk/execution features (#6/#7/#8) — validated WITHOUT sending a real order. Real money stays OFF.

**Architecture:** Reuse the M1/M2 core unchanged. M3 adds: a pre-arm account-mode check in the go-live gate; a `DryRunExchange` wrapper that passes reads through to the real mainnet adapter but intercepts writes; config-driven correlation groups + a macro-blackout calendar in the RiskManager; partial-TP/breakeven scale-out in the engine+adapter; and three hardening seams. Spot path is byte-for-byte unchanged.

**Tech Stack:** Python 3.12, `ccxt.async_support`, pytest + `unittest.mock`. No new dependencies.

## Global Constraints

- **`LIVE_TRADING_ENABLED` stays `false` — real money is OFF.** M3 builds + validates capability only; no task arms real-money mainnet trading. A test asserts the gate still blocks real arming.
- **Spot path unchanged.** `exchange/binance.py`, `exchange/paper.py`, and the spot branches of `risk/manager.py`, `core/engine.py`, `main.py` must not change behavior. Every new feature is futures-gated and/or default-off so spot/legacy runs are identical.
- **Mainnet validation = dry-run only.** The `DryRunExchange` is the vehicle; it must NEVER reach an order endpoint. The M2 futures-testnet contract test is unchanged.
- **Risk-first invariants (do not regress):** isolated margin, one-way (`positionSide="BOTH"`), no auto-flip, exits/closes are NEVER blocked by any new gate (correlation, blackout), never-naked (place protective before cancelling the old one).
- **Backward-compatible defaults:** correlation default reproduces today's `{BTC/USDT, ETH/USDT}` exactly when unset; `LOOPn_PARTIAL_TP_PCT` default `0` = today's full-close-at-TP behavior; missing macro-blackout file = no blackout.
- Test runner: `.venv/bin/python -m pytest`.

---

## File Structure (M3)

- Create `exchange/dry_run.py` — `DryRunExchange(Exchange)` delegating wrapper (C2).
- Create `tests/test_dry_run.py`.
- Create `config/macro_blackout.json` (empty `[]` seed) + `core/macro_blackout.py` loader (C4).
- Create `tests/test_macro_blackout.py`.
- Create `docs/mainnet-futures-runbook.md` (C7).
- Modify `exchange/binance_futures.py` — `verify_account_mode` (C1); live leverage-tier mmr (C6b); sized reduce-only partial-TP order + stop cancel-replace (C5a).
- Modify `main.py` — gate one-way enforcement (C1); `DRY_RUN` wrapping (C2); config-time leverage-conflict rejection (C6c).
- Modify `risk/manager.py` — correlation groups (C3); macro-blackout open-gate (C4); live-tier mmr threading + slippage pad (C6b/C6c).
- Modify `core/engine.py` — partial-TP/breakeven scale-out, futures, default-off (C5b).
- Modify `core/strategy_runtime.py` + `core/loop_config.py` — `partial_tp_pct` field + parse (C5c); correlation/blackout env.
- Modify `docs/release-safety-validation-gate.md` — futures gate commands (C7).
- Modify `tests/test_go_live_safety.py` — futures one-way refusal + LIVE_TRADING_ENABLED still gates.

---

# PART A — Safety core (C1 + C2)

## Task 1: Go-live gate — futures one-way + isolated enforcement (C1)

**Files:**
- Modify: `exchange/binance_futures.py`, `main.py`
- Test: `tests/test_binance_futures_exchange.py` (add), `tests/test_go_live_safety.py` (add)

**Interfaces:**
- Produces: `async BinanceFuturesExchange.verify_account_mode() -> None` — raises `ValueError` if the account is NOT in one-way position mode (queries `fetch_position_mode` / the dapi/fapi position-side-dual flag via ccxt). `_validate_go_live_safety` calls it for each LIVE futures loop before arming.

- [ ] **Step 1: Write the failing test (adapter)**

```python
# tests/test_binance_futures_exchange.py (add)
@pytest.mark.asyncio
async def test_verify_account_mode_raises_on_hedge(fx):
    fx._exchange.fetch_position_mode = AsyncMock(return_value={"dualSidePosition": True})  # hedge
    with pytest.raises(ValueError, match="one-way"):
        await fx.verify_account_mode()

@pytest.mark.asyncio
async def test_verify_account_mode_ok_on_one_way(fx):
    fx._exchange.fetch_position_mode = AsyncMock(return_value={"dualSidePosition": False})
    await fx.verify_account_mode()  # must not raise
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_binance_futures_exchange.py -k verify_account_mode -v`
Expected: FAIL — `AttributeError: ... 'verify_account_mode'`.

- [ ] **Step 3: Implement `verify_account_mode`**

```python
# exchange/binance_futures.py
    async def verify_account_mode(self) -> None:
        """Pre-arm safety: refuse to trade real money unless the account is in one-way
        position mode. Hedge mode breaks our positionSide='BOTH' + no-auto-flip model."""
        try:
            mode = await self._exchange.fetch_position_mode()
        except Exception as exc:
            raise ValueError(f"cannot verify futures position mode before arming: {exc}")
        if mode.get("dualSidePosition") is True:
            raise ValueError("Binance account is in HEDGE mode; one-way mode is required for futures trading")
```

- [ ] **Step 4: Wire into the go-live gate**

In `main.py` `_validate_go_live_safety`, after the existing key/host checks, add a futures-only pre-arm assertion. Because the gate is sync and `verify_account_mode` is async, perform the check where the live futures exchange is built (in `run()` after `_build_live_exchange_for`, before the engine loop starts): for each live futures `spec.exchange`, `await spec.exchange.verify_account_mode()`. Guard: only when `not paper_mode and spec.config.market == "futures"` and `isinstance(spec.exchange, BinanceFuturesExchange)`. A raise aborts startup.

- [ ] **Step 5: Write the gate test**

```python
# tests/test_go_live_safety.py (add) — match the file's existing style
@pytest.mark.asyncio
async def test_live_futures_refuses_hedge_account(monkeypatch):
    # Build a fake futures exchange whose verify_account_mode raises; assert startup aborts.
    # Reuse the file's existing harness for constructing a live-futures spec; the key assertion
    # is that a ValueError("one-way"/"HEDGE") propagates and no engine loop starts.
    ...
```
Write it concretely against the existing `tests/test_go_live_safety.py` harness.

- [ ] **Step 6: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_binance_futures_exchange.py tests/test_go_live_safety.py -q`
```bash
git add exchange/binance_futures.py main.py tests/test_binance_futures_exchange.py tests/test_go_live_safety.py
git commit -m "feat(futures): go-live gate refuses hedge-mode accounts before arming

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Mainnet dry-run mode — `DryRunExchange` wrapper (C2)

**Files:**
- Create: `exchange/dry_run.py`
- Test: `tests/test_dry_run.py`
- Modify: `main.py` (DRY_RUN wrapping)

**Interfaces:**
- Produces: `DryRunExchange(wrapped: Exchange)` implementing `Exchange`. Read methods (`fetch_ohlcv`, `get_balance`, `get_positions`, `fetch_funding_rate`, `seed_open_positions`, `enforce_liquidation_buffer` read part) DELEGATE to `wrapped`. Write methods (`place_order`, `protect_position`, `cancel_order`) LOG `WOULD …` and return synthetic results without delegating. `main` wraps the live exchange in `DryRunExchange` when `DRY_RUN=true`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_dry_run.py
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock
from core.models import Order
from exchange.dry_run import DryRunExchange

def _order(side="BUY", qty=0.01, reduce_only=False):
    return Order(id="o1", symbol="BTC/USDT", side=side, type="MARKET", quantity=qty,
                 price=None, status="PENDING", exchange_order_id=None, reduce_only=reduce_only)

@pytest.fixture
def wrapped():
    w = MagicMock()
    w.get_balance = AsyncMock(return_value={"USDT": 5000.0})
    w.get_positions = AsyncMock(return_value=[])
    w.fetch_funding_rate = AsyncMock(return_value=0.0001)
    w.fetch_ohlcv = AsyncMock(return_value=[[1, 2, 3, 4, 5, 6]])
    w.place_order = AsyncMock()
    w.protect_position = AsyncMock()
    w.cancel_order = AsyncMock()
    return w

@pytest.mark.asyncio
async def test_reads_pass_through(wrapped):
    dr = DryRunExchange(wrapped)
    assert await dr.get_balance() == {"USDT": 5000.0}
    assert await dr.fetch_funding_rate("BTC/USDT") == 0.0001
    wrapped.get_balance.assert_awaited_once()

@pytest.mark.asyncio
async def test_place_order_does_not_touch_wrapped(wrapped, caplog):
    dr = DryRunExchange(wrapped)
    with caplog.at_level(logging.WARNING):
        filled = await dr.place_order(_order(), current_price=65000.0)
    wrapped.place_order.assert_not_awaited()        # NEVER reaches the real adapter
    assert filled.status == "FILLED"
    assert "WOULD" in caplog.text

@pytest.mark.asyncio
async def test_protect_and_cancel_do_not_touch_wrapped(wrapped):
    dr = DryRunExchange(wrapped)
    await dr.protect_position("BTC/USDT", side="BUY", quantity=0.01, take_profit=1, stop_loss=1)
    await dr.cancel_order("x", "BTC/USDT")
    wrapped.protect_position.assert_not_awaited()
    wrapped.cancel_order.assert_not_awaited()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dry_run.py -v`
Expected: FAIL — `ModuleNotFoundError: exchange.dry_run`.

- [ ] **Step 3: Implement the wrapper**

```python
# exchange/dry_run.py
import logging
from core.models import Order, Position
from exchange.base import Exchange

logger = logging.getLogger(__name__)


class DryRunExchange(Exchange):
    """Wrap a real exchange so the full live path runs against real market/account data,
    but NO order ever reaches the venue. Reads delegate; writes log 'WOULD ...' and return
    synthetic results. ponytail: thin delegating wrapper — duplicating the adapter would drift."""

    def __init__(self, wrapped: Exchange):
        self._wrapped = wrapped

    # --- reads: delegate ---
    async def fetch_ohlcv(self, symbol, timeframe, limit):
        return await self._wrapped.fetch_ohlcv(symbol, timeframe, limit)

    async def get_balance(self):
        return await self._wrapped.get_balance()

    async def get_positions(self):
        return await self._wrapped.get_positions()

    async def fetch_funding_rate(self, symbol):
        return await self._wrapped.fetch_funding_rate(symbol)

    async def seed_open_positions(self, symbols):
        return await self._wrapped.seed_open_positions(symbols)

    async def close(self):
        close = getattr(self._wrapped, "close", None)
        if close is not None:
            await close()

    # --- writes: intercept, never delegate ---
    async def place_order(self, order: Order, current_price: float = 0.0, stop_price=None) -> Order:
        logger.warning("DRY-RUN: WOULD place %s %s qty=%s reduce_only=%s @~%s",
                       order.side, order.symbol, order.quantity, order.reduce_only, current_price)
        filled = order.__class__(**order.__dict__)
        filled.status = "FILLED"
        filled.exchange_order_id = f"dry-{order.id}"
        return filled

    async def protect_position(self, symbol, side, quantity, take_profit, stop_loss,
                               current_price=0.0, strategy_id="") -> Order | None:
        logger.warning("DRY-RUN: WOULD protect %s side=%s qty=%s tp=%s sl=%s",
                       symbol, side, quantity, take_profit, stop_loss)
        if stop_loss is None:
            return None
        return Order(id=f"dry-stop-{symbol}", symbol=symbol,
                     side="SELL" if side.upper() == "BUY" else "BUY", type="STOP_MARKET",
                     quantity=quantity, price=stop_loss, status="OPEN",
                     exchange_order_id=f"dry-stop-{symbol}", reduce_only=True, strategy_id=strategy_id)

    async def cancel_order(self, order_id, symbol) -> None:
        logger.warning("DRY-RUN: WOULD cancel %s on %s", order_id, symbol)

    async def enforce_liquidation_buffer(self, symbol, current_price, buffer_pct, stop_loss) -> str:
        # Read the real liq via the wrapped adapter but never add margin / close.
        action = "ok"
        try:
            pos = next((p for p in await self._wrapped.get_positions() if p.symbol == symbol), None)
            if pos and pos.liquidation_price and current_price > 0:
                dist = abs(current_price - pos.liquidation_price) / current_price
                if dist < buffer_pct:
                    logger.warning("DRY-RUN: WOULD add margin / close %s (liq %.4f within buffer)",
                                   symbol, pos.liquidation_price)
                    action = "would_act"
        except Exception:
            pass
        return action
```

- [ ] **Step 4: Wire `DRY_RUN` in main**

In `main.py`, after `_build_live_exchange_for(...)` builds the live exchange, wrap it when `_env_bool("DRY_RUN", False)`:
```python
        spec.exchange = _build_live_exchange_for(spec.config, settings, exchange)
        if _env_bool("DRY_RUN", False) and not paper_mode:
            from exchange.dry_run import DryRunExchange
            spec.exchange = DryRunExchange(spec.exchange)
            logger.warning("DRY-RUN mode: connected to live venue for data; NO orders will be sent")
```
(Match the real assignment structure in `main.py` — the controller will confirm the exact lines at dispatch.)

- [ ] **Step 5: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_dry_run.py -q`
```bash
git add exchange/dry_run.py tests/test_dry_run.py main.py
git commit -m "feat: DryRunExchange — run the full live path with no orders sent

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# PART B — Hardening seams (C6)

## Task 3: Config-time leverage-conflict rejection (C6c)

**Files:**
- Modify: `core/loop_config.py` (or wherever multi-loop configs are assembled in `main.py`)
- Test: `tests/test_loop_config.py` (add)

**Interfaces:**
- Produces: a validation that raises `ValueError` if two futures loops set a DIFFERENT `LEVERAGE` on the SAME symbol (one symbol = one leverage). Closes the cross-loop leverage race the M2 review flagged.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_loop_config.py (add)
def test_two_futures_loops_same_symbol_diff_leverage_rejected():
    env = {
        "LOOP1_STRATEGY": "ema_cross", "LOOP1_SYMBOL": "BTC/USDT", "LOOP1_MARKET": "futures", "LOOP1_LEVERAGE": "3",
        "LOOP2_STRATEGY": "rsi_macd", "LOOP2_SYMBOL": "BTC/USDT", "LOOP2_MARKET": "futures", "LOOP2_LEVERAGE": "5",
    }
    with pytest.raises(ValueError, match="same symbol.*leverage|leverage.*BTC/USDT"):
        validate_loop_leverage_consistency(parse_all_loops(env))  # match the file's real parse entrypoint

def test_two_futures_loops_same_symbol_same_leverage_ok():
    env = {
        "LOOP1_STRATEGY": "ema_cross", "LOOP1_SYMBOL": "BTC/USDT", "LOOP1_MARKET": "futures", "LOOP1_LEVERAGE": "3",
        "LOOP2_STRATEGY": "rsi_macd", "LOOP2_SYMBOL": "BTC/USDT", "LOOP2_MARKET": "futures", "LOOP2_LEVERAGE": "3",
    }
    validate_loop_leverage_consistency(parse_all_loops(env))  # must not raise
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_loop_config.py -k leverage_consist -v`
Expected: FAIL — function missing.

- [ ] **Step 3: Implement**

```python
# core/loop_config.py
def validate_loop_leverage_consistency(configs) -> None:
    """One symbol = one leverage across all futures loops. Two adapters can't share a
    per-symbol leverage setting on Binance, so diverging leverage on the same symbol is a
    config error (M2 cross-loop race). ponytail: config-time rejection is the simplest guard."""
    by_symbol: dict[str, int] = {}
    for cfg in configs:
        if getattr(cfg, "market", "spot") != "futures":
            continue
        prev = by_symbol.get(cfg.symbol)
        if prev is not None and prev != cfg.leverage:
            raise ValueError(
                f"two futures loops set different leverage on the same symbol {cfg.symbol} "
                f"({prev} vs {cfg.leverage}); one symbol = one leverage"
            )
        by_symbol[cfg.symbol] = cfg.leverage
```
Call `validate_loop_leverage_consistency(runtime_configs)` in `main.run()` right after the configs are parsed (near `_validate_go_live_safety`).

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_loop_config.py -q`
```bash
git add core/loop_config.py main.py tests/test_loop_config.py
git commit -m "feat(config): reject diverging leverage on same symbol across futures loops

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Live maintenance-margin tier in the pre-trade liq estimate (C6b)

**Files:**
- Modify: `exchange/binance_futures.py`, `risk/manager.py`, `core/engine.py`
- Test: `tests/test_binance_futures_exchange.py`, `tests/test_risk_manager.py`

**Interfaces:**
- Produces: `async BinanceFuturesExchange.maintenance_margin_rate(symbol) -> float` from `fetch_leverage_tiers` (lowest applicable tier's `maintenanceMarginRate`, biased to the FIRST/most-conservative tier; falls back to `MMR_DEFAULT` on error). The engine passes this real mmr into `risk.evaluate(..., mmr=...)` for the live futures path (paper keeps `MMR_DEFAULT`).

- [ ] **Step 1: Write the failing test (adapter)**

```python
# tests/test_binance_futures_exchange.py (add)
@pytest.mark.asyncio
async def test_maintenance_margin_rate_from_tiers(fx):
    fx._exchange.fetch_leverage_tiers = AsyncMock(return_value={
        "BTC/USDT": [{"maintenanceMarginRate": 0.004}, {"maintenanceMarginRate": 0.01}],
    })
    assert await fx.maintenance_margin_rate("BTC/USDT") == 0.004

@pytest.mark.asyncio
async def test_maintenance_margin_rate_falls_back(fx):
    from exchange.futures_math import MMR_DEFAULT
    fx._exchange.fetch_leverage_tiers = AsyncMock(side_effect=Exception("no tiers"))
    assert await fx.maintenance_margin_rate("BTC/USDT") == MMR_DEFAULT
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_binance_futures_exchange.py -k maintenance_margin_rate -v`
Expected: FAIL — method missing.

- [ ] **Step 3: Implement adapter method**

```python
# exchange/binance_futures.py
    async def maintenance_margin_rate(self, symbol: str) -> float:
        """Real maintenance-margin rate from the venue's leverage tiers (conservative:
        first tier). Flat MMR_DEFAULT is too optimistic for alts. Falls back on error."""
        from exchange.futures_math import MMR_DEFAULT
        try:
            tiers = await self._exchange.fetch_leverage_tiers([symbol])
            rows = tiers.get(symbol) or []
            if rows:
                return float(rows[0].get("maintenanceMarginRate") or MMR_DEFAULT)
        except Exception:
            pass
        return MMR_DEFAULT
```

- [ ] **Step 4: Thread into the engine's live evaluate**

In `core/engine.py`, where the futures funding is fetched before `evaluate` (M2 added this), ALSO fetch the live mmr when the exchange supports it and pass it:
```python
        mmr = MMR_DEFAULT
        if self._market == "futures" and hasattr(self.exchange, "maintenance_margin_rate"):
            try:
                mmr = await self.exchange.maintenance_margin_rate(self.symbol)
            except Exception:
                mmr = MMR_DEFAULT
```
and add `mmr=mmr` to the `self._risk_manager.evaluate(...)` call. Import `MMR_DEFAULT` from `exchange.futures_math`. Paper exchanges have no `maintenance_margin_rate` → keep `MMR_DEFAULT` (behavior unchanged).

- [ ] **Step 5: Add a risk test that a higher mmr tightens the liq guard**

```python
# tests/test_risk_manager.py (add)
def test_higher_mmr_tightens_liquidation_guard(rm):
    # same entry/stop/leverage: a larger mmr moves liq closer to entry, so a stop that
    # passed at MMR_DEFAULT is rejected at a higher mmr.
    sig = make_signal(side="BUY", entry=100.0, sl=90.0, conf=0.9)
    assert rm.evaluate(sig, {"USDT": 1000.0}, [], market="futures", leverage=10,
                       risk_per_trade=0.01, mmr=0.005) is not None
    assert rm.evaluate(sig, {"USDT": 1000.0}, [], market="futures", leverage=10,
                       risk_per_trade=0.01, mmr=0.05) is None
    assert rm.last_rejection_reason == "liquidation_too_close"
```
(Pick entry/sl/leverage so the two mmr values straddle the guard; the implementer tunes the numbers so the assertion holds against the real `liquidation_price` formula.)

- [ ] **Step 6: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_binance_futures_exchange.py tests/test_risk_manager.py tests/test_engine.py -q`
```bash
git add exchange/binance_futures.py core/engine.py risk/manager.py tests/test_binance_futures_exchange.py tests/test_risk_manager.py
git commit -m "feat(futures): live pre-trade liq guard uses real leverage-tier mmr

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Slippage pad on the pre-trade liq guard (C6b reconcile)

**Files:**
- Modify: `risk/manager.py`
- Test: `tests/test_risk_manager.py` (add)

**Interfaces:**
- Consumes: existing `evaluate(..., liq_buffer_pct=...)`.
- Produces: the pre-trade liquidation guard widens the buffer by a `slippage_pad` so the guard accounts for the exchange liquidating on the slippage-adjusted fill (always slightly tighter than `entry_price`). Add kwarg `slippage_pad: float = 0.0` (default keeps current behavior); effective buffer = `liq_buffer_pct + slippage_pad`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_risk_manager.py (add)
def test_slippage_pad_widens_liq_guard(rm):
    sig = make_signal(side="BUY", entry=100.0, sl=92.0, conf=0.9)
    # passes with no pad...
    assert rm.evaluate(sig, {"USDT": 1000.0}, [], market="futures", leverage=10,
                       risk_per_trade=0.01) is not None
    # ...rejected once a slippage pad pushes the buffered liq above the stop
    assert rm.evaluate(sig, {"USDT": 1000.0}, [], market="futures", leverage=10,
                       risk_per_trade=0.01, slippage_pad=0.05) is None
    assert rm.last_rejection_reason == "liquidation_too_close"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_risk_manager.py -k slippage_pad -v`
Expected: FAIL — unexpected kwarg / assertion (no pad applied).

- [ ] **Step 3: Implement**

In `risk/manager.py` `evaluate`, add `slippage_pad: float = 0.0` to the keyword-only block, and in the liquidation-guard block change the buffered-liq computation to use `(liq_buffer_pct + slippage_pad)` instead of `liq_buffer_pct`:
```python
            eff_buffer = liq_buffer_pct + slippage_pad
            buffered_liq = liq * (1 - eff_buffer) if side_ls == "LONG" else liq * (1 + eff_buffer)
```
(Tune the test numbers so the pad straddles the guard. Thread `slippage_pad` from a new env `LIQ_SLIPPAGE_PAD` via the engine/main like `liq_buffer_pct`; default 0.0 keeps behavior.)

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_risk_manager.py -q`
```bash
git add risk/manager.py tests/test_risk_manager.py
git commit -m "feat(risk): slippage pad on pre-trade liq guard (exchange-liq is tighter than entry)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# PART C — Risk features (C3 + C4)

## Task 6: Config-driven correlation groups (C3, #7)

**Files:**
- Modify: `risk/manager.py`, `main.py`
- Test: `tests/test_risk_manager.py` (add)

**Interfaces:**
- Produces: `RiskManager(..., correlation_groups: list[set[str]] | None = None)`. Default `None` → `[{"BTC/USDT", "ETH/USDT"}]` (today's behavior EXACTLY). The correlation gate rejects an open whose group already holds another symbol; reason `correlation_filter` (unchanged). `main` parses `CORRELATION_GROUPS="BTC/USDT,ETH/USDT;SOL/USDT,AVAX/USDT"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_risk_manager.py (add)
def test_default_correlation_groups_match_btc_eth(rm_factory):
    rm = rm_factory()  # no correlation_groups -> default {BTC,ETH}
    # holding ETH blocks opening BTC (today's behavior)
    held = [make_position("ETH/USDT")]
    sig = make_signal(side="BUY", symbol="BTC/USDT", entry=100, sl=95, conf=0.9)
    assert rm.evaluate(sig, {"USDT": 1000.0}, held) is None
    assert rm.last_rejection_reason == "correlation_filter"

def test_custom_group_blocks_within_group_only(rm_factory):
    rm = rm_factory(correlation_groups=[{"SOL/USDT", "AVAX/USDT"}])
    held = [make_position("SOL/USDT")]
    # AVAX blocked (same group)
    assert rm.evaluate(make_signal(side="BUY", symbol="AVAX/USDT", entry=100, sl=95, conf=0.9),
                       {"USDT": 1000.0}, held) is None
    # BTC NOT blocked (not in any configured group now)
    assert rm.evaluate(make_signal(side="BUY", symbol="BTC/USDT", entry=100, sl=95, conf=0.9),
                       {"USDT": 1000.0}, held) is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_risk_manager.py -k correlation -v`
Expected: FAIL — `correlation_groups` kwarg / behavior missing.

- [ ] **Step 3: Implement**

In `risk/manager.py` `__init__`, add `correlation_groups: list[set[str]] | None = None` and store
`self._correlation_groups = correlation_groups or [{"BTC/USDT", "ETH/USDT"}]`.
Replace the hardcoded block (`risk/manager.py:147-152`):
```python
        group = next((g for g in self._correlation_groups if signal.symbol in g), None)
        if opening and group is not None:
            if any(p.symbol in group and p.symbol != signal.symbol for p in positions):
                self._last_rejection_reason = "correlation_filter"
                return None
```
In `main.py`, parse `CORRELATION_GROUPS` (semicolon groups, comma symbols) into `list[set[str]]` and pass to `RiskManager(...)`; unset → pass `None`.

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_risk_manager.py -q`
```bash
git add risk/manager.py main.py tests/test_risk_manager.py
git commit -m "feat(risk): config-driven correlation groups (default = today's BTC/ETH)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Macro-event blackout window (C4, #8)

**Files:**
- Create: `core/macro_blackout.py`, `config/macro_blackout.json`
- Modify: `risk/manager.py`, `main.py`
- Test: `tests/test_macro_blackout.py`, `tests/test_risk_manager.py` (add)

**Interfaces:**
- Produces: `core.macro_blackout.load_blackout(path) -> list[tuple[datetime, datetime]]` and `in_blackout(windows, now) -> bool`. `RiskManager(..., blackout_windows=None)` rejects OPENS (never exits) when `now` is inside a window; reason `macro_blackout`. `now` is injectable for tests.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_macro_blackout.py
from datetime import datetime, timezone
from core.macro_blackout import in_blackout

def _w(s, e): return (datetime.fromisoformat(s), datetime.fromisoformat(e))

def test_in_blackout_true_inside():
    w = [_w("2026-06-20T12:00:00+00:00", "2026-06-20T14:00:00+00:00")]
    assert in_blackout(w, datetime(2026, 6, 20, 13, 0, tzinfo=timezone.utc)) is True

def test_in_blackout_false_outside():
    w = [_w("2026-06-20T12:00:00+00:00", "2026-06-20T14:00:00+00:00")]
    assert in_blackout(w, datetime(2026, 6, 20, 15, 0, tzinfo=timezone.utc)) is False
```
```python
# tests/test_risk_manager.py (add)
def test_blackout_blocks_open_not_exit(rm_factory):
    from datetime import datetime, timezone
    w = [(datetime(2026,6,20,12,tzinfo=timezone.utc), datetime(2026,6,20,14,tzinfo=timezone.utc))]
    now = datetime(2026,6,20,13,tzinfo=timezone.utc)
    rm = rm_factory(blackout_windows=w)
    # OPEN blocked
    assert rm.evaluate(make_signal(side="BUY", symbol="BTC/USDT", entry=100, sl=95, conf=0.9),
                       {"USDT": 1000.0}, [], now=now) is None
    assert rm.last_rejection_reason == "macro_blackout"
    # spot SELL EXIT on a held position NOT blocked
    held = [make_position("BTC/USDT")]
    assert rm.evaluate(make_signal(side="SELL", symbol="BTC/USDT", entry=100, sl=105, conf=0.9),
                       {"USDT": 1000.0}, held, now=now) is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_macro_blackout.py tests/test_risk_manager.py -k blackout -v`
Expected: FAIL — module / kwarg missing.

- [ ] **Step 3: Implement loader + seed config**

```python
# core/macro_blackout.py
import json
from datetime import datetime

def load_blackout(path: str) -> list[tuple[datetime, datetime]]:
    """Load UTC blackout windows from a JSON list of {start,end,label}. Missing file = []."""
    try:
        with open(path) as f:
            rows = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for r in rows:
        out.append((datetime.fromisoformat(r["start"]), datetime.fromisoformat(r["end"])))
    return out

def in_blackout(windows, now: datetime) -> bool:
    return any(start <= now <= end for start, end in windows)
```
Create `config/macro_blackout.json` with `[]`.

- [ ] **Step 4: Wire into RiskManager**

Add `blackout_windows=None` to `__init__` (store `self._blackout_windows = blackout_windows or []`) and a `now: datetime | None = None` kwarg to `evaluate`. In the gate sequence — AFTER the HOLD/missing-stop checks and BEFORE sizing, gated on `opening` only:
```python
        if opening and self._blackout_windows:
            from core.macro_blackout import in_blackout
            from datetime import datetime, timezone
            if in_blackout(self._blackout_windows, now or datetime.now(timezone.utc)):
                self._last_rejection_reason = "macro_blackout"
                return None
```
In `main.py`, `load_blackout(os.getenv("MACRO_BLACKOUT_FILE", "config/macro_blackout.json"))` and pass to `RiskManager`.

- [ ] **Step 5: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_macro_blackout.py tests/test_risk_manager.py -q`
```bash
git add core/macro_blackout.py config/macro_blackout.json risk/manager.py main.py tests/test_macro_blackout.py tests/test_risk_manager.py
git commit -m "feat(risk): macro-event blackout blocks opens (never exits)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# PART D — Execution: partial-TP + breakeven (C5, #6)

## Task 8: Adapter — sized reduce-only partial TP + stop cancel-replace (C5a)

**Files:**
- Modify: `exchange/binance_futures.py`, `exchange/paper_futures.py`
- Test: `tests/test_binance_futures_exchange.py`, `tests/test_paper_futures.py`

**Interfaces:**
- Produces: `async BinanceFuturesExchange.partial_take_profit(symbol, side, quantity, current_price) -> Order` — a SIZED reduce-only MARKET order (NOT `closePosition`) closing `quantity` of the position. And `async move_stop_to_breakeven(symbol, side, quantity, entry_price, old_stop_order_id) -> Order` — place a new STOP at `entry_price` (closePosition, MARK) FIRST, then cancel the old stop (never-naked). Paper equivalents update its position bookkeeping.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_binance_futures_exchange.py (add)
@pytest.mark.asyncio
async def test_partial_take_profit_is_sized_reduce_only(fx_orders):
    await fx_orders.partial_take_profit("BTC/USDT", side="LONG", quantity=0.005, current_price=66000.0)
    _, kwargs = fx_orders._exchange.create_order.call_args
    assert kwargs["params"]["reduceOnly"] is True
    assert "closePosition" not in kwargs["params"]   # sized partial, not full close
    assert kwargs["amount"] == 0.005
    assert kwargs["side"] == "sell"                  # exit side of a long

@pytest.mark.asyncio
async def test_move_stop_to_breakeven_places_before_cancel(fx_protect):
    calls = []
    fx_protect._exchange.create_order = AsyncMock(side_effect=lambda **k: calls.append(("create", k)) or {"id": "be-1"})
    fx_protect._exchange.cancel_order = AsyncMock(side_effect=lambda *a: calls.append(("cancel", a)))
    await fx_protect.move_stop_to_breakeven("BTC/USDT", side="LONG", quantity=0.005,
                                            entry_price=65000.0, old_stop_order_id="old-1")
    assert calls[0][0] == "create" and calls[1][0] == "cancel"   # never-naked: new stop first
    assert calls[0][1]["params"]["stopPrice"] == 65000.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_binance_futures_exchange.py -k "partial_take_profit or move_stop_to_breakeven" -v`
Expected: FAIL — methods missing.

- [ ] **Step 3: Implement**

```python
# exchange/binance_futures.py
    async def partial_take_profit(self, symbol, side, quantity, current_price=0.0) -> Order:
        exit_side = "sell" if side.upper() == "LONG" else "buy"
        amount = self._round_amount(symbol, quantity)
        result = await self._exchange.create_order(
            symbol=symbol, type="market", side=exit_side, amount=amount, price=None,
            params={"reduceOnly": True, "positionSide": "BOTH"},
        )
        return Order(id=f"ptp-{symbol}", symbol=symbol, side=exit_side.upper(), type="MARKET",
                     quantity=amount, price=None, status="FILLED",
                     exchange_order_id=str(result.get("id", "")), reduce_only=True)

    async def move_stop_to_breakeven(self, symbol, side, quantity, entry_price, old_stop_order_id) -> Order:
        # Never-naked: place the new breakeven STOP, THEN cancel the old one.
        exit_side = "sell" if side.upper() == "LONG" else "buy"
        new = await self._exchange.create_order(
            symbol=symbol, type="STOP_MARKET", side=exit_side, amount=None, price=None,
            params={"closePosition": True, "workingType": "MARK_PRICE",
                    "stopPrice": self._exchange.price_to_precision(symbol, entry_price),
                    "positionSide": "BOTH"},
        )
        if old_stop_order_id:
            await self.cancel_order(old_stop_order_id, symbol)
        return Order(id=f"be-{symbol}", symbol=symbol, side=exit_side.upper(), type="STOP_MARKET",
                     quantity=quantity, price=entry_price, status="OPEN",
                     exchange_order_id=str(new.get("id", "")), reduce_only=True)
```
Add paper-futures equivalents in `exchange/paper_futures.py` that reduce the tracked position quantity by the partial amount and reset its stop to `entry_price` (so the paper bench and tests can exercise the engine path).

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_binance_futures_exchange.py tests/test_paper_futures.py -q`
```bash
git add exchange/binance_futures.py exchange/paper_futures.py tests/test_binance_futures_exchange.py tests/test_paper_futures.py
git commit -m "feat(futures): sized reduce-only partial-TP + never-naked breakeven stop move

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: Engine — partial-TP at TP1 + breakeven (futures, default-off) (C5b)

**Files:**
- Modify: `core/engine.py`
- Test: `tests/test_engine.py` (add)

**Interfaces:**
- Consumes: `partial_take_profit`, `move_stop_to_breakeven` (Task 8); `partial_tp_pct` engine kwarg (Task 10).
- Produces: in the futures candle path, when a held position's price reaches `signal.take_profit` (TP1) and the position hasn't been partially closed yet AND `self._partial_tp_pct > 0`, close `partial_tp_pct` of it via `partial_take_profit` and move its stop to breakeven once. Tracked in `self._partial_done: set[symbol]`. Default `partial_tp_pct=0` → never triggers (today's behavior).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_engine.py (add — reuse the CapturingPaperFuturesExchange harness)
# test_partial_tp_triggers_once_at_tp1_then_breakeven:
#   futures engine, partial_tp_pct=0.5, open a LONG with take_profit=T; feed a candle whose
#   high >= T -> assert a sized reduce-only partial close was issued for ~half the qty AND the
#   stop moved to entry (breakeven); feed another candle past T -> assert NO second partial
#   (tracked done). Use AsyncMock spies on partial_take_profit/move_stop_to_breakeven.
# test_partial_tp_off_by_default:
#   partial_tp_pct=0 (default) -> reaching TP1 does NOT call partial_take_profit (today's
#   full-close-at-TP behavior via the protective TP order is unchanged).
```
Write both concretely against the futures engine harness; spy the two adapter methods.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_engine.py -k partial_tp -v`
Expected: FAIL — partial logic absent.

- [ ] **Step 3: Implement**

Add `self._partial_done: set[str] = set()` in `__init__`. In the futures branch of `process_candle` (after `get_positions`, alongside the liq-buffer / time-stop handling), add — gated on `self._partial_tp_pct > 0` and a held position whose `high >= take_profit` (track the entry TP via `_opened_at`-style state or read from the signal that opened it; the engine already stores active-decision context — reuse it, else stash `tp` when arming). On trigger:
```python
        if self._market == "futures" and self._partial_tp_pct > 0:
            held = self._find_futures_position(futures_positions, self.symbol)
            tp = self._partial_tp_target.get(self.symbol)
            if held is not None and tp is not None and self.symbol not in self._partial_done \
               and ((held.side == "LONG" and high >= tp) or (held.side == "SHORT" and low <= tp)):
                qty = round(held.quantity * self._partial_tp_pct, 8)
                await self.exchange.partial_take_profit(self.symbol, held.side, qty, current_price)
                await self.exchange.move_stop_to_breakeven(self.symbol, held.side,
                    held.quantity - qty, held.entry_price, self._stop_order_id.get(self.symbol))
                self._partial_done.add(self.symbol)
```
Record `self._partial_tp_target[symbol] = signal.take_profit` and `self._stop_order_id[symbol] = prot.exchange_order_id` when a futures position is opened (in the open/protect block), and clear all three (`_partial_done`, `_partial_tp_target`, `_stop_order_id`) when the position closes (in `_close_futures_position`). The controller will confirm the exact open/close hooks at dispatch.

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_engine.py -q`
```bash
git add core/engine.py tests/test_engine.py
git commit -m "feat(engine): futures partial-TP at TP1 + move SL to breakeven (default-off)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: Config — `LOOPn_PARTIAL_TP_PCT` + wiring (C5c)

**Files:**
- Modify: `core/strategy_runtime.py`, `core/loop_config.py`, `main.py`
- Test: `tests/test_loop_config.py` (add)

**Interfaces:**
- Produces: per-loop `partial_tp_pct: float = 0.0` field + `LOOPn_PARTIAL_TP_PCT` parse (0..1; reject out-of-range). Threaded into the futures `engine_kwargs` in `main` as `partial_tp_pct`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_loop_config.py (add)
def test_partial_tp_pct_default_zero():
    cfg = parse_one_loop(env={"LOOP1_STRATEGY": "ema_cross", "LOOP1_MARKET": "futures", "LOOP1_LEVERAGE": "3"}, prefix="LOOP1_")
    assert cfg.partial_tp_pct == 0.0

def test_partial_tp_pct_parsed_and_range_checked():
    cfg = parse_one_loop(env={"LOOP1_STRATEGY": "ema_cross", "LOOP1_MARKET": "futures", "LOOP1_LEVERAGE": "3",
                              "LOOP1_PARTIAL_TP_PCT": "0.5"}, prefix="LOOP1_")
    assert cfg.partial_tp_pct == 0.5
    with pytest.raises(ValueError):
        parse_one_loop(env={"LOOP1_STRATEGY": "ema_cross", "LOOP1_MARKET": "futures",
                            "LOOP1_LEVERAGE": "3", "LOOP1_PARTIAL_TP_PCT": "1.5"}, prefix="LOOP1_")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_loop_config.py -k partial_tp_pct -v`
Expected: FAIL — field/parse missing.

- [ ] **Step 3: Implement**

Add `partial_tp_pct: float = 0.0` to `core/strategy_runtime.py`. In `core/loop_config.py` parse:
```python
        partial_tp_pct = float(lp.get("PARTIAL_TP_PCT", env.get("PARTIAL_TP_PCT", "0")))
        if not 0.0 <= partial_tp_pct <= 1.0:
            raise ValueError(f"{prefix}PARTIAL_TP_PCT={partial_tp_pct} must be in [0,1]")
```
Pass `partial_tp_pct=partial_tp_pct` in both the default and parsed construction blocks. In `main.py`, add `"partial_tp_pct": spec.config.partial_tp_pct,` to the futures `engine_kwargs`.

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_loop_config.py -q`
```bash
git add core/strategy_runtime.py core/loop_config.py main.py tests/test_loop_config.py
git commit -m "feat(config): LOOPn_PARTIAL_TP_PCT (0..1, default 0=off)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# PART E — Runbook + gate docs (C7)

## Task 11: Mainnet runbook + release-safety gate wiring + LIVE-OFF assertion

**Files:**
- Create: `docs/mainnet-futures-runbook.md`
- Modify: `docs/release-safety-validation-gate.md`
- Test: `tests/test_go_live_safety.py` (add)

**Interfaces:**
- Produces: the ordered mainnet-via-dry-run validation steps + the explicit "real money stays off until a validated strategy" rule; a test asserting `LIVE_TRADING_ENABLED=false` still blocks real arming (the M3 master constraint).

- [ ] **Step 1: Write the LIVE-OFF assertion test**

```python
# tests/test_go_live_safety.py (add)
def test_live_futures_still_blocked_without_live_trading_enabled(monkeypatch):
    # A LIVE futures runtime with LIVE_TRADING_ENABLED unset/false must still raise the
    # existing "set LIVE_TRADING_ENABLED=true to arm" error — M3 must NOT have armed real money.
    ...
```
Write concretely against the existing `_validate_go_live_safety` harness (reuse the file's helpers).

- [ ] **Step 2: Run to verify it passes against current code**

Run: `.venv/bin/python -m pytest tests/test_go_live_safety.py -k still_blocked -v`
Expected: PASS (this is a guard test locking the constraint; it should pass on current code and keep passing).

- [ ] **Step 3: Write the runbook**

Create `docs/mainnet-futures-runbook.md` with: prerequisites (testnet contract test green; M2+M3 suites green); the **dry-run** validation procedure (`DRY_RUN=true` + mainnet keys, confirm `WOULD …` logs and zero orders on the venue); the gate checklist (one-way verified, `LIQ_BUFFER_PCT>0`, correlation/blackout config, leverage-consistency); and the **"DO NOT set `LIVE_TRADING_ENABLED=true` until a strategy is validated profitable (the #2/§10 work)"** rule, in bold, at the top.

- [ ] **Step 4: Wire futures into the release-safety gate**

In `docs/release-safety-validation-gate.md`, add the futures commands to the standard set:
`.venv/bin/python -m pytest tests/test_binance_futures_exchange.py tests/test_dry_run.py tests/test_go_live_safety.py -q` and a line that the futures-testnet contract test (`RUN_CONTRACT_TESTS=1 ... test_contract_binance_futures_testnet.py`) is required evidence for any change to the live futures path.

- [ ] **Step 5: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_go_live_safety.py -q && .venv/bin/python -m pytest -q`
```bash
git add docs/mainnet-futures-runbook.md docs/release-safety-validation-gate.md tests/test_go_live_safety.py
git commit -m "docs: mainnet futures runbook + release-safety gate wiring; lock LIVE-OFF

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## M3 Exit Gate

- [ ] Full suite green: `.venv/bin/python -m pytest -q` (offline; contract tests skipped).
- [ ] Spot path unchanged — spot adapter + spot engine/risk tests pass untouched.
- [ ] **LIVE_TRADING_ENABLED still false** — the guard test passes; no task armed real money.
- [ ] **Dry-run validated** (user, with mainnet keys): `DRY_RUN=true` connects to the venue, logs `WOULD …`, and the venue shows ZERO orders/positions opened by the bot.
- [ ] Defaults backward-compatible: correlation `{BTC,ETH}` unchanged when unset; `PARTIAL_TP_PCT=0` = full-close behavior; missing blackout file = no blackout.

---

## Self-Review notes

- **Spec coverage:** C1→Task 1; C2→Task 2; C6c(leverage race)→Task 3; C6b(mmr tier)→Task 4; C6b(slippage pad/reconcile)→Task 5; C3(correlation)→Task 6; C4(blackout)→Task 7; C5a(adapter partial-TP/breakeven)→Task 8; C5b(engine)→Task 9; C5c(config)→Task 10; C7(runbook+gate+LIVE-OFF)→Task 11.
- **Placeholders:** Task 1 Step 5, Task 9 Step 1, and Task 11 Step 1 are described against existing harnesses (`tests/test_go_live_safety.py`, the futures `tests/test_engine.py` harness) rather than reproduced verbatim because they must reuse those files' fixtures — the implementer writes them concretely from the named behaviors. The controller will confirm the exact open/close hooks for Task 9's partial-TP state and the main.py wiring lines for Tasks 2/3/6/7 at dispatch (as in M2). All other code/test steps are concrete.
- **Type consistency:** `verify_account_mode()->None`, `maintenance_margin_rate(symbol)->float`, `partial_take_profit(symbol, side, quantity, current_price)->Order`, `move_stop_to_breakeven(symbol, side, quantity, entry_price, old_stop_order_id)->Order`, `DryRunExchange(wrapped)`, `RiskManager(..., correlation_groups, blackout_windows)`, `evaluate(..., mmr, slippage_pad, now)`, `partial_tp_pct`, `validate_loop_leverage_consistency(configs)`, `load_blackout(path)`/`in_blackout(windows, now)` — used consistently across tasks.
- **Real-money OFF** is enforced by Task 11's guard test + the Global Constraints; no task sets `LIVE_TRADING_ENABLED`.
