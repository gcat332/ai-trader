# Futures M2 — Binance USDT-M Testnet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire a real Binance USDT-M perpetual-futures adapter (testnet-first) onto the unchanged M1 core, plus funding-rate gating, exchange-truth liquidation handling, and the per-(market,network) live wiring — gated by a futures-testnet contract test.

**Architecture:** New `BinanceFuturesExchange` implements the same `Exchange` ABC as paper/spot (`ccxt.async_support.binance`, `defaultType:"future"`, sandbox for testnet). M1 core (models, engine, risk, paper exchange, config) is reused; the only core edits thread funding + a post-open liquidation-buffer enforcement through the existing seams. Spot path is byte-for-byte unchanged. The expert-trader design consult (verdict GO-WITH-CHANGES) is folded in: `closePosition=true` brackets on MARK price, stop-first-never-naked, exchange-reported `liquidationPrice` as truth, real leverage tiers for the pre-trade estimate, and a per-symbol leverage race guard.

**Tech Stack:** Python 3.11, `ccxt.async_support`, pytest + `unittest.mock` (AsyncMock/MagicMock), aiosqlite. No new dependencies.

## Global Constraints

- **Spot path unchanged.** `exchange/binance.py`, `exchange/paper.py`, and the spot branches of `risk/manager.py`, `core/engine.py`, `main.py` must not change behavior. Spot adapters return `0.0` from any new funding hook and are exempt from every futures-only gate.
- **Isolated margin, one-way position mode.** Every futures order carries `positionSide="BOTH"`. Never hedge-mode.
- **No auto-flip.** An opposite signal only closes (reduce-only); it never reverses in one evaluation. (M1 invariant — do not regress.)
- **Risk-first.** When in doubt, the safe action is *don't open* / *protect the position*, never *take more risk*. Hard loss ceiling ~10% of all assets.
- **Sensitive areas** (`risk/manager.py` sizing/gates, `core/engine.py` order flow, exchange order execution): change only with focused tests and an explicit old-vs-new behavior note in the commit body.
- **Live network is opt-in.** Contract tests hit the network only when `RUN_CONTRACT_TESTS=1`. Never commit `.env`, keys, logs, or db artifacts.
- **mmr constant** lives once: `MMR_DEFAULT = 0.005` in `exchange/futures_math.py`. Funding skip threshold default: `FUNDING_SKIP_THRESHOLD = 0.001` (0.1%/8h). Liquidation buffer default: existing `liq_buffer_pct`.
- **Funding "pays" rule:** opening a LONG pays when `funding_rate > 0`; opening a SHORT pays when `funding_rate < 0`.
- Test runner: `.venv/bin/python -m pytest`. Async tests use the existing `@pytest.mark.asyncio` / asyncio mode already configured in the repo.

---

## File Structure (M2)

- Create `exchange/binance_futures.py` — `BinanceFuturesExchange(Exchange)`; all live USDT-M behavior. The single large new file; kept cohesive because every method shares the one ccxt client + symbol-state.
- Create `tests/test_binance_futures_exchange.py` — mocked-ccxt unit tests (mirrors `tests/test_binance_exchange.py`).
- Create `tests/test_contract_binance_futures_testnet.py` — opt-in real-testnet contract test.
- Create `analysis/select_strategy_futures.py` — thin wrapper re-running §9 selection on `market="futures"`.
- Create `tests/test_select_strategy_futures.py`.
- Modify `exchange/futures_math.py` — add `MMR_DEFAULT` constant; default `mmr` params reference it.
- Modify `exchange/base.py` — add `fetch_funding_rate` (default `0.0`) + `add_margin`/`enforce_liquidation_buffer` default no-ops to the ABC.
- Modify `exchange/paper.py`, `exchange/paper_futures.py` — inherit the `0.0` funding default (paper) / no-op buffer enforcement; import `MMR_DEFAULT` in `paper_futures`.
- Modify `risk/manager.py` — `MMR_DEFAULT` import; funding skip gate in `evaluate`.
- Modify `core/engine.py` — fetch funding before `risk.evaluate`; call `enforce_liquidation_buffer` after a futures open.
- Modify `core/loop_config.py` + `core/strategy_runtime.py` — `funding_skip_threshold` per-loop field + parse.
- Modify `main.py` — per-(market,network) exchange isolation; thread futures engine kwargs in LIVE too; pass `funding_skip_threshold`.

---

# Task 1: mmr shared constant

**Files:**
- Modify: `exchange/futures_math.py`
- Modify: `risk/manager.py` (import + default)
- Modify: `exchange/paper_futures.py` (import + default)
- Test: `tests/test_futures_math.py` (add)

**Interfaces:**
- Produces: `exchange.futures_math.MMR_DEFAULT: float = 0.005`. `liquidation_price(side, entry, leverage, mmr=MMR_DEFAULT)`, `RiskManager.evaluate(..., mmr=MMR_DEFAULT)`, `PaperFuturesExchange(..., mmr=MMR_DEFAULT)` all reference the one constant.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_futures_math.py  (add)
def test_mmr_default_is_single_source_of_truth():
    from exchange.futures_math import MMR_DEFAULT
    import inspect
    from risk.manager import RiskManager
    from exchange.paper_futures import PaperFuturesExchange
    assert MMR_DEFAULT == 0.005
    # the literal 0.005 must no longer be hard-coded as a default in the consumers
    assert inspect.signature(RiskManager.evaluate).parameters["mmr"].default == MMR_DEFAULT
    assert inspect.signature(PaperFuturesExchange.__init__).parameters["mmr"].default == MMR_DEFAULT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_futures_math.py::test_mmr_default_is_single_source_of_truth -v`
Expected: FAIL — `ImportError: cannot import name 'MMR_DEFAULT'`.

- [ ] **Step 3: Add the constant and re-point the defaults**

In `exchange/futures_math.py`, near the top (after the module docstring):

```python
# ponytail: one maintenance-margin-rate source for paper sim + pre-trade liq estimate.
# Live trading ignores this — it trusts the exchange-reported liquidationPrice (and
# real leverage tiers). Flat 0.005 is the low BTC/ETH tier; alts are higher, so the
# pre-trade estimate is deliberately optimistic-but-only-for-paper. Upgrade path:
# pull per-symbol tiers from fetchLeverageTiers() (live does this in M2).
MMR_DEFAULT = 0.005
```

Change `def liquidation_price(side, entry, leverage, mmr=0.005)` → `mmr=MMR_DEFAULT`.
In `risk/manager.py`, add `from exchange.futures_math import liquidation_price, MMR_DEFAULT` (extend the existing import) and change the `evaluate` default `mmr=0.005` → `mmr=MMR_DEFAULT`.
In `exchange/paper_futures.py`, add `from exchange.futures_math import ..., MMR_DEFAULT` and change `__init__` default `mmr=0.005` → `mmr=MMR_DEFAULT`.

- [ ] **Step 4: Run the targeted test + the two consumers' suites**

Run: `.venv/bin/python -m pytest tests/test_futures_math.py tests/test_risk_manager.py tests/test_paper_futures.py -q`
Expected: PASS (no behavior change — same numeric default).

- [ ] **Step 5: Commit**

```bash
git add exchange/futures_math.py risk/manager.py exchange/paper_futures.py tests/test_futures_math.py
git commit -m "refactor: single MMR_DEFAULT constant for paper + pre-trade liq estimate

Old: 0.005 hard-coded as the default in liquidation_price, RiskManager.evaluate,
and PaperFuturesExchange — coupled only by coincident literals.
New: one MMR_DEFAULT in futures_math, imported by both consumers. Identical numeric
behavior; removes the coincidence flagged by the M1 whole-branch review.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# Task 2: `fetch_funding_rate` on the Exchange ABC (spot/paper return 0.0)

**Files:**
- Modify: `exchange/base.py`
- Test: `tests/test_paper_exchange.py` (add), `tests/test_paper_exchange_tick.py` (none)

**Interfaces:**
- Produces: `Exchange.fetch_funding_rate(symbol: str) -> float` — default returns `0.0` (no funding concept). Spot (`BinanceExchange`) and both paper exchanges inherit the default, so the funding gate is a no-op for them.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_paper_exchange.py  (add)
import pytest

@pytest.mark.asyncio
async def test_paper_exchange_funding_rate_is_zero():
    from exchange.paper import PaperExchange
    ex = PaperExchange(initial_balance={"USDT": 1000.0})
    assert await ex.fetch_funding_rate("BTC/USDT") == 0.0

@pytest.mark.asyncio
async def test_paper_futures_funding_rate_is_zero():
    from exchange.paper_futures import PaperFuturesExchange
    ex = PaperFuturesExchange({"USDT": 1000.0}, leverage=5)
    assert await ex.fetch_funding_rate("BTC/USDT") == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_paper_exchange.py -k funding_rate -v`
Expected: FAIL — `AttributeError: 'PaperExchange' object has no attribute 'fetch_funding_rate'`.

- [ ] **Step 3: Add the default to the ABC**

In `exchange/base.py`, add a concrete (non-abstract) default method to `Exchange`:

```python
    async def fetch_funding_rate(self, symbol: str) -> float:
        """Current funding rate for a perpetual symbol (e.g. 0.0001 = 0.01%/8h).
        Default 0.0 — spot and paper have no funding, so the funding gate never
        blocks them. Live USDT-M overrides with the venue rate."""
        return 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_paper_exchange.py -k funding_rate -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add exchange/base.py tests/test_paper_exchange.py
git commit -m "feat: add Exchange.fetch_funding_rate hook (default 0.0)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# Task 3: Funding skip gate in RiskManager.evaluate

**Files:**
- Modify: `risk/manager.py`
- Test: `tests/test_risk_manager.py` (add)

**Interfaces:**
- Consumes: existing `evaluate(self, signal, balance, positions, *, market, leverage, risk_per_trade, mmr, liq_buffer_pct)`.
- Produces: two new kwargs `funding_rate: float = 0.0`, `funding_threshold: float = 0.001`. New rejection reason `"funding_adverse"`. Gate runs only for futures opens, AFTER the liquidation guard and BEFORE sizing (so a structurally-ineligible trade still reports its more specific reason).

**Old-vs-new behavior note (for the commit):** spot and any call that omits `funding_rate` (default 0.0) are unaffected — `abs(0.0) > threshold` is always false. Only a futures open whose side *pays* funding above the threshold is newly rejected.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_risk_manager.py  (add — reuse this file's existing signal/balance helpers)
# Assumes a helper that builds a high-confidence signal with valid futures stops;
# match the file's existing fixtures (e.g. make_signal(side=, entry=, sl=, conf=)).

def test_long_skipped_when_positive_funding_exceeds_threshold(rm):
    # LONG pays funding when rate>0; 0.0012 > 0.001 default -> skip
    sig = make_signal(side="BUY", entry=100.0, sl=95.0, conf=0.9)
    order = rm.evaluate(sig, {"USDT": 1000.0}, [], market="futures", leverage=5,
                        risk_per_trade=0.01, funding_rate=0.0012)
    assert order is None
    assert rm.last_rejection_reason == "funding_adverse"

def test_short_skipped_when_negative_funding_exceeds_threshold(rm):
    # SHORT pays funding when rate<0
    sig = make_signal(side="SELL", entry=100.0, sl=105.0, conf=0.9)
    order = rm.evaluate(sig, {"USDT": 1000.0}, [], market="futures", leverage=5,
                        risk_per_trade=0.01, funding_rate=-0.0012)
    assert order is None
    assert rm.last_rejection_reason == "funding_adverse"

def test_long_allowed_when_funding_negative(rm):
    # LONG RECEIVES funding when rate<0 -> never blocked, however large
    sig = make_signal(side="BUY", entry=100.0, sl=95.0, conf=0.9)
    order = rm.evaluate(sig, {"USDT": 1000.0}, [], market="futures", leverage=5,
                        risk_per_trade=0.01, funding_rate=-0.05)
    assert order is not None

def test_funding_below_threshold_allowed(rm):
    sig = make_signal(side="BUY", entry=100.0, sl=95.0, conf=0.9)
    order = rm.evaluate(sig, {"USDT": 1000.0}, [], market="futures", leverage=5,
                        risk_per_trade=0.01, funding_rate=0.0005)  # < 0.001
    assert order is not None

def test_spot_ignores_funding(rm):
    sig = make_signal(side="BUY", entry=100.0, sl=95.0, conf=0.9)
    order = rm.evaluate(sig, {"USDT": 1000.0}, [], market="spot", funding_rate=0.05)
    assert order is not None
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_risk_manager.py -k funding -v`
Expected: FAIL — `evaluate() got an unexpected keyword argument 'funding_rate'`.

- [ ] **Step 3: Add the kwargs + gate**

In `risk/manager.py`, extend the `evaluate` signature:

```python
        mmr=MMR_DEFAULT,
        liq_buffer_pct=0.0,
        funding_rate=0.0,
        funding_threshold=0.001,
    ) -> Order | None:
```

Insert the gate immediately AFTER the liquidation-guard block (right after the `if side_ls == "SHORT" and signal.stop_loss >= buffered_liq:` return, still inside `if is_futures and opening:`), BEFORE the `usdt = balance.get(...)` sizing line:

```python
            # Funding skip: only blocks when THIS side pays funding and the rate is
            # extreme (squeeze territory). Cheap funding is noise vs trade EV, so it is
            # not gated. LONG pays when rate>0; SHORT pays when rate<0.
            side_pays = (signal.side == "BUY" and funding_rate > 0) or \
                        (signal.side == "SELL" and funding_rate < 0)
            if side_pays and abs(funding_rate) > funding_threshold:
                self._last_rejection_reason = "funding_adverse"
                return None
```

- [ ] **Step 4: Run to verify pass + no regression**

Run: `.venv/bin/python -m pytest tests/test_risk_manager.py -q`
Expected: PASS (all existing risk tests + the five new ones).

- [ ] **Step 5: Commit**

```bash
git add risk/manager.py tests/test_risk_manager.py
git commit -m "feat(risk): funding skip gate for futures opens

Old: futures opens passed regardless of funding rate.
New: a futures open whose side PAYS funding (long & rate>0 / short & rate<0) is
rejected (funding_adverse) when abs(rate) > funding_threshold (default 0.001 =
0.1%/8h, extreme/squeeze level). Spot and rate-omitted calls unaffected (default 0.0).
Threshold is high by design — cheap funding is noise vs trade EV (trader consult).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# Task 4: `BinanceFuturesExchange` — construction, market data, balance, funding

**Files:**
- Create: `exchange/binance_futures.py`
- Test: `tests/test_binance_futures_exchange.py`

**Interfaces:**
- Produces: `BinanceFuturesExchange(api_key, api_secret, testnet=True, leverage=1)` implementing `Exchange`. This task lands: `__init__` (futures ccxt client, sandbox, one-way mode deferred to Task 5), `fetch_ohlcv` (retry loop), `get_balance` (USDT free), `fetch_funding_rate` (real), `close`. Order/position methods are stubbed `raise NotImplementedError` until their tasks.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_binance_futures_exchange.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from exchange.binance_futures import BinanceFuturesExchange


@pytest.fixture
def fx():
    with patch("exchange.binance_futures.ccxt.binance") as MockBinance:
        m = MagicMock()
        m.fetch_ohlcv = AsyncMock(return_value=[[1700000000000, 65000.0, 65500.0, 64500.0, 65200.0, 100.0]])
        m.fetch_balance = AsyncMock(return_value={"USDT": {"free": 5000.0}})
        m.fetch_funding_rate = AsyncMock(return_value={"fundingRate": 0.0001})
        m.set_sandbox_mode = MagicMock()
        m.set_position_mode = AsyncMock()
        m.close = AsyncMock()
        MockBinance.return_value = m
        yield BinanceFuturesExchange(api_key="k", api_secret="s", testnet=True, leverage=5)


@pytest.mark.asyncio
async def test_init_uses_future_market_and_sandbox(fx):
    # defaultType future + sandbox on for testnet
    args, kwargs = fx._exchange_init_args
    assert kwargs["options"]["defaultType"] == "future"
    fx._exchange.set_sandbox_mode.assert_called_once_with(True)

@pytest.mark.asyncio
async def test_fetch_ohlcv(fx):
    candles = await fx.fetch_ohlcv("BTC/USDT", "1h", limit=1)
    assert candles[0][4] == 65200.0

@pytest.mark.asyncio
async def test_get_balance_returns_usdt_free(fx):
    bal = await fx.get_balance()
    assert bal["USDT"] == 5000.0

@pytest.mark.asyncio
async def test_fetch_funding_rate_returns_float(fx):
    assert await fx.fetch_funding_rate("BTC/USDT") == 0.0001
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_binance_futures_exchange.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'exchange.binance_futures'`.

- [ ] **Step 3: Create the adapter skeleton**

```python
# exchange/binance_futures.py
import asyncio
import ccxt.async_support as ccxt
from core.models import Order, Position
from exchange.base import Exchange


class BinanceFuturesExchange(Exchange):
    """Binance USDT-M linear perpetuals (testnet-first). One-way, isolated margin.

    ponytail: deliberately a single cohesive file — every method shares the one ccxt
    client plus per-symbol leverage/margin state, so splitting by method would just
    scatter that shared state."""

    def __init__(self, api_key: str, api_secret: str, testnet: bool = True,
                 leverage: int = 1):
        self.leverage = leverage
        self._leverage_set: set[str] = set()   # symbols whose leverage/margin we configured
        self._lev_lock = asyncio.Lock()        # serialize per-symbol account-state writes
        init_kwargs = {
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            # Linear USDT-M only; keep ccxt from loading coin-margined (dapi) markets.
            "options": {"defaultType": "future", "fetchMarkets": ["linear"]},
        }
        self._exchange_init_args = ((), init_kwargs)  # captured for tests
        self._exchange = ccxt.binance(init_kwargs)
        if testnet:
            self._exchange.set_sandbox_mode(True)

    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int,
                          max_retries: int = 5) -> list[list]:
        delay = 5.0
        for attempt in range(max_retries):
            try:
                return await self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            except Exception:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(min(delay, 300.0))
                delay *= 2
        return []

    async def fetch_funding_rate(self, symbol: str) -> float:
        data = await self._exchange.fetch_funding_rate(symbol)
        return float(data.get("fundingRate") or 0.0)

    async def get_balance(self) -> dict[str, float]:
        raw = await self._exchange.fetch_balance()
        usdt = raw.get("USDT", {})
        free = float(usdt.get("free", 0.0)) if isinstance(usdt, dict) else 0.0
        return {"USDT": free}

    async def place_order(self, order: Order, current_price: float = 0.0,
                          stop_price: float | None = None) -> Order:
        raise NotImplementedError  # Task 6

    async def protect_position(self, symbol, side, quantity, take_profit, stop_loss,
                               current_price=0.0, strategy_id="") -> Order | None:
        raise NotImplementedError  # Task 7

    async def cancel_order(self, order_id: str, symbol: str) -> None:
        raise NotImplementedError  # Task 7

    async def get_positions(self) -> list[Position]:
        raise NotImplementedError  # Task 8

    async def close(self) -> None:
        await self._exchange.close()
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_binance_futures_exchange.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add exchange/binance_futures.py tests/test_binance_futures_exchange.py
git commit -m "feat: BinanceFuturesExchange skeleton (init, ohlcv, balance, funding)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# Task 5: Leverage + isolated margin setup with per-symbol race guard

**Files:**
- Modify: `exchange/binance_futures.py`
- Test: `tests/test_binance_futures_exchange.py` (add)

**Interfaces:**
- Produces: `async _ensure_symbol_config(symbol) -> int` — sets one-way mode (once), per-symbol `set_margin_mode("isolated")` + `set_leverage(self.leverage)` under a lock, read-back-verifies the actual leverage from `fetch_positions`/`fetch_leverage_tiers`, caches the symbol in `_leverage_set`, returns the effective leverage. Idempotent. Benign on "no need to change" / "position open" errors (logs, continues). Consumed by `place_order` (Task 6).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_binance_futures_exchange.py  (add)
@pytest.mark.asyncio
async def test_ensure_symbol_config_sets_isolated_and_leverage_once(fx):
    fx._exchange.set_margin_mode = AsyncMock()
    fx._exchange.set_leverage = AsyncMock()
    fx._exchange.fetch_positions = AsyncMock(return_value=[{"symbol": "BTC/USDT", "leverage": 5}])
    lev = await fx._ensure_symbol_config("BTC/USDT")
    assert lev == 5
    fx._exchange.set_margin_mode.assert_awaited_once_with("isolated", "BTC/USDT")
    fx._exchange.set_leverage.assert_awaited_once_with(5, "BTC/USDT")
    # second call is a no-op (cached) — no extra account-state writes
    await fx._ensure_symbol_config("BTC/USDT")
    assert fx._exchange.set_leverage.await_count == 1

@pytest.mark.asyncio
async def test_ensure_symbol_config_tolerates_already_set_errors(fx):
    fx._exchange.set_margin_mode = AsyncMock(side_effect=Exception("-4046 No need to change margin type"))
    fx._exchange.set_leverage = AsyncMock(side_effect=Exception("-4028 leverage not modified"))
    fx._exchange.fetch_positions = AsyncMock(return_value=[{"symbol": "BTC/USDT", "leverage": 5}])
    lev = await fx._ensure_symbol_config("BTC/USDT")  # must not raise
    assert lev == 5
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_binance_futures_exchange.py -k ensure_symbol_config -v`
Expected: FAIL — `AttributeError: ... '_ensure_symbol_config'`.

- [ ] **Step 3: Implement**

Add to `BinanceFuturesExchange`:

```python
    async def _ensure_symbol_config(self, symbol: str) -> int:
        """Set one-way mode + isolated margin + leverage for a symbol, once, serialized.
        Leverage/margin-mode are per-symbol ACCOUNT state (not per-order), so two loops
        on the same symbol would race; the lock + cache make it set-once. Read-back the
        real leverage so sizing uses what the venue actually applied. Benign on the
        'already set' / 'position open' rejections Binance raises."""
        if symbol in self._leverage_set:
            return self.leverage
        async with self._lev_lock:
            if symbol in self._leverage_set:
                return self.leverage
            if not getattr(self, "_position_mode_set", False):
                try:
                    await self._exchange.set_position_mode(False)  # one-way
                except Exception:
                    pass  # already one-way, or not togglable with an open position
                self._position_mode_set = True
            try:
                await self._exchange.set_margin_mode("isolated", symbol)
            except Exception:
                pass  # -4046 no need to change / position already open
            try:
                await self._exchange.set_leverage(self.leverage, symbol)
            except Exception:
                pass  # -4028 not modified / open position
            effective = self.leverage
            try:
                for p in await self._exchange.fetch_positions([symbol]):
                    if p.get("symbol") == symbol and p.get("leverage"):
                        effective = int(p["leverage"])
                        break
            except Exception:
                pass
            self.leverage = effective
            self._leverage_set.add(symbol)
            return effective
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_binance_futures_exchange.py -k ensure_symbol_config -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add exchange/binance_futures.py tests/test_binance_futures_exchange.py
git commit -m "feat(futures): per-symbol leverage/isolated setup with race guard

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# Task 6: `place_order` — market open + reduce-only exit, step/min-notional, benign reduce-only-no-position

**Files:**
- Modify: `exchange/binance_futures.py`
- Test: `tests/test_binance_futures_exchange.py` (add)

**Interfaces:**
- Consumes: `_ensure_symbol_config` (Task 5).
- Produces: `place_order(order, current_price=0.0, stop_price=None) -> Order`. Opens with `positionSide="BOTH"`; exits (`order.reduce_only`) add `reduceOnly=True`. Rounds amount to step + validates min-notional (returns the order with `status="FAILED"` and `quantity=0` if below min, so nothing naked is opened; `"FAILED"` is the engine's reject sentinel — `engine.py` guards entry with `!= "FAILED"`). A `-2022 ReduceOnly rejected` on an exit returns `status="FILLED"` (position already flat — idempotent, benign).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_binance_futures_exchange.py  (add)
from core.models import Order

def _order(side, qty, reduce_only=False):
    return Order(id="o1", symbol="BTC/USDT", side=side, type="MARKET", quantity=qty,
                 price=None, status="PENDING", exchange_order_id=None, reduce_only=reduce_only)

@pytest.fixture
def fx_orders(fx):
    fx._exchange.market = MagicMock(return_value={"limits": {"cost": {"min": 5.0}}})
    fx._exchange.amount_to_precision = MagicMock(side_effect=lambda s, a: round(a, 3))
    fx._exchange.set_margin_mode = AsyncMock()
    fx._exchange.set_leverage = AsyncMock()
    fx._exchange.fetch_positions = AsyncMock(return_value=[{"symbol": "BTC/USDT", "leverage": 5}])
    fx._exchange.create_order = AsyncMock(return_value={"id": "ex-1", "status": "closed", "average": 65000.0})
    return fx

@pytest.mark.asyncio
async def test_open_long_market(fx_orders):
    filled = await fx_orders.place_order(_order("BUY", 0.01), current_price=65000.0)
    assert filled.status == "FILLED"
    assert filled.exchange_order_id == "ex-1"
    _, kwargs = fx_orders._exchange.create_order.call_args
    assert kwargs["params"]["positionSide"] == "BOTH"
    assert "reduceOnly" not in kwargs["params"]

@pytest.mark.asyncio
async def test_exit_is_reduce_only(fx_orders):
    await fx_orders.place_order(_order("SELL", 0.01, reduce_only=True), current_price=65000.0)
    _, kwargs = fx_orders._exchange.create_order.call_args
    assert kwargs["params"]["reduceOnly"] is True

@pytest.mark.asyncio
async def test_below_min_notional_rejected_not_opened(fx_orders):
    # 0.00001 * 65000 = 0.65 USDT < 5.0 min -> never sent
    filled = await fx_orders.place_order(_order("BUY", 0.00001), current_price=65000.0)
    assert filled.status == "FAILED"
    assert filled.quantity == 0
    fx_orders._exchange.create_order.assert_not_called()

@pytest.mark.asyncio
async def test_reduce_only_no_position_is_benign(fx_orders):
    fx_orders._exchange.create_order = AsyncMock(side_effect=Exception("binance -2022 ReduceOnly Order is rejected"))
    filled = await fx_orders.place_order(_order("SELL", 0.01, reduce_only=True), current_price=65000.0)
    assert filled.status == "FILLED"  # already flat — treat as a no-op success
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_binance_futures_exchange.py -k "open_long or reduce_only or min_notional" -v`
Expected: FAIL — `NotImplementedError`.

- [ ] **Step 3: Implement**

Replace the `place_order` stub:

```python
    def _round_amount(self, symbol: str, quantity: float) -> float:
        try:
            return float(self._exchange.amount_to_precision(symbol, quantity))
        except Exception:
            return quantity

    def _min_notional(self, symbol: str) -> float:
        try:
            return float(self._exchange.market(symbol)["limits"]["cost"]["min"] or 0.0)
        except Exception:
            return 0.0

    async def place_order(self, order: Order, current_price: float = 0.0,
                          stop_price: float | None = None) -> Order:
        filled = order.__class__(**order.__dict__)
        await self._ensure_symbol_config(order.symbol)
        amount = self._round_amount(order.symbol, order.quantity)
        ref_px = current_price or order.price or 0.0
        # Risk-first: a sub-min order would be silently rejected by Binance, leaving an
        # unprotected/half-entered state. Refuse it here instead.
        if not order.reduce_only and ref_px > 0 and amount * ref_px < self._min_notional(order.symbol):
            filled.status = "FAILED"  # engine reject sentinel (engine.py guards != "FAILED")
            filled.quantity = 0
            return filled
        params = {"positionSide": "BOTH", "newClientOrderId": order.id[:36]}
        if order.reduce_only:
            params["reduceOnly"] = True
        try:
            result = await self._exchange.create_order(
                symbol=order.symbol, type="market", side=order.side.lower(),
                amount=amount, price=None, params=params,
            )
        except Exception as exc:
            # A reduce-only exit on an already-flat position is a benign no-op.
            if order.reduce_only and "-2022" in str(exc):
                filled.status = "FILLED"
                return filled
            raise
        filled.exchange_order_id = str(result.get("id", ""))
        filled.status = "FILLED" if result.get("status") == "closed" else "OPEN"
        return filled
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_binance_futures_exchange.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add exchange/binance_futures.py tests/test_binance_futures_exchange.py
git commit -m "feat(futures): market open + reduce-only exit (step/min-notional, -2022 benign)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# Task 7: `protect_position` — closePosition brackets on MARK price, stop-first, cancel_order

**Files:**
- Modify: `exchange/binance_futures.py`
- Test: `tests/test_binance_futures_exchange.py` (add)

**Interfaces:**
- Consumes: `place_order` (for the emergency market-close), `_ensure_symbol_config`.
- Produces: `protect_position(symbol, side, quantity, take_profit, stop_loss, current_price=0.0, strategy_id="") -> Order | None`. Places a `STOP_MARKET` (`closePosition=true`, `workingType=MARK_PRICE`) FIRST; if that raises, immediately market-closes the position (reduce-only) and re-raises so the caller knows. Then places a `TAKE_PROFIT_MARKET` (`closePosition=true`) if `take_profit` given (a TP failure is non-fatal — the stop already protects). Returns the protective STOP `Order` (its `exchange_order_id` set). Also lands `cancel_order`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_binance_futures_exchange.py  (add)
@pytest.fixture
def fx_protect(fx_orders):
    fx_orders._exchange.create_order = AsyncMock(side_effect=[
        {"id": "stop-1", "status": "open"},   # STOP_MARKET placed first
        {"id": "tp-1", "status": "open"},      # TAKE_PROFIT_MARKET second
    ])
    fx_orders._exchange.price_to_precision = MagicMock(side_effect=lambda s, p: p)
    return fx_orders

@pytest.mark.asyncio
async def test_protect_places_stop_first_with_mark_and_closeposition(fx_protect):
    prot = await fx_protect.protect_position("BTC/USDT", side="BUY", quantity=0.01,
                                             take_profit=66000.0, stop_loss=64000.0, current_price=65000.0)
    first = fx_protect._exchange.create_order.call_args_list[0]
    assert first.kwargs["type"] == "STOP_MARKET"
    assert first.kwargs["side"] == "sell"            # exit side of a long
    assert first.kwargs["params"]["closePosition"] is True
    assert first.kwargs["params"]["workingType"] == "MARK_PRICE"
    assert first.kwargs["params"]["stopPrice"] == 64000.0
    second = fx_protect._exchange.create_order.call_args_list[1]
    assert second.kwargs["type"] == "TAKE_PROFIT_MARKET"
    assert prot.exchange_order_id == "stop-1"

@pytest.mark.asyncio
async def test_stop_failure_triggers_emergency_close(fx_protect):
    fx_protect._exchange.create_order = AsyncMock(side_effect=Exception("stop rejected"))
    # spy the reduce-only market close
    closes = []
    orig = fx_protect.place_order
    async def spy(order, **kw):
        if order.reduce_only:
            closes.append(order)
            return order
        return await orig(order, **kw)
    fx_protect.place_order = spy
    with pytest.raises(Exception):
        await fx_protect.protect_position("BTC/USDT", side="BUY", quantity=0.01,
                                          take_profit=None, stop_loss=64000.0, current_price=65000.0)
    assert closes and closes[0].reduce_only and closes[0].side == "SELL"

@pytest.mark.asyncio
async def test_short_protect_exit_side_is_buy(fx_protect):
    prot = await fx_protect.protect_position("BTC/USDT", side="SELL", quantity=0.01,
                                             take_profit=64000.0, stop_loss=66000.0, current_price=65000.0)
    assert fx_protect._exchange.create_order.call_args_list[0].kwargs["side"] == "buy"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_binance_futures_exchange.py -k protect -v`
Expected: FAIL — `NotImplementedError`.

- [ ] **Step 3: Implement**

Replace the `protect_position` + `cancel_order` stubs:

```python
    async def protect_position(self, symbol, side, quantity, take_profit, stop_loss,
                               current_price=0.0, strategy_id="") -> Order | None:
        """closePosition=true STOP + TP brackets. Stop goes first and on MARK price so
        the bot's stop and the liquidation engine read the same price; if the stop fails
        to place we do NOT sit naked — we market-close immediately and re-raise."""
        if stop_loss is None:
            return None
        exit_side = "sell" if side.upper() == "BUY" else "buy"
        # STOP first.
        try:
            stop = await self._exchange.create_order(
                symbol=symbol, type="STOP_MARKET", side=exit_side, amount=None, price=None,
                params={"closePosition": True, "workingType": "MARK_PRICE",
                        "stopPrice": self._exchange.price_to_precision(symbol, stop_loss),
                        "positionSide": "BOTH"},
            )
        except Exception:
            emergency = Order(id=f"emg-{symbol}", symbol=symbol,
                              side="SELL" if side.upper() == "BUY" else "BUY",
                              type="MARKET", quantity=quantity, price=None,
                              status="PENDING", exchange_order_id=None,
                              reduce_only=True, strategy_id=strategy_id)
            await self.place_order(emergency, current_price=current_price)
            raise
        protective = Order(id=f"stop-{symbol}", symbol=symbol,
                           side="SELL" if side.upper() == "BUY" else "BUY",
                           type="STOP_MARKET", quantity=quantity, price=stop_loss,
                           status="OPEN", exchange_order_id=str(stop.get("id", "")),
                           reduce_only=True, strategy_id=strategy_id)
        # TP second — non-fatal; the stop already protects the downside.
        if take_profit is not None:
            try:
                await self._exchange.create_order(
                    symbol=symbol, type="TAKE_PROFIT_MARKET", side=exit_side, amount=None, price=None,
                    params={"closePosition": True, "workingType": "MARK_PRICE",
                            "stopPrice": self._exchange.price_to_precision(symbol, take_profit),
                            "positionSide": "BOTH"},
                )
            except Exception:
                pass
        return protective

    async def cancel_order(self, order_id: str, symbol: str) -> None:
        try:
            await self._exchange.cancel_order(order_id, symbol)
        except Exception:
            pass  # already filled/canceled — benign
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_binance_futures_exchange.py -k protect -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add exchange/binance_futures.py tests/test_binance_futures_exchange.py
git commit -m "feat(futures): closePosition STOP+TP brackets on MARK, stop-first never-naked

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# Task 8: `get_positions` + `seed_open_positions` — exchange-truth liquidationPrice + orphan reconciliation

**Files:**
- Modify: `exchange/binance_futures.py`
- Test: `tests/test_binance_futures_exchange.py` (add)

**Interfaces:**
- Produces: `get_positions() -> list[Position]` from real `fetch_positions` — maps `side` (`long`/`short` → `LONG`/`SHORT`), `entryPrice`, `contracts` (abs), `unrealizedPnl`, `leverage`, and the venue-reported `liquidationPrice` straight onto `Position.liquidation_price` (no formula). `seed_open_positions(symbols)` cancels orphaned protective orders for flat symbols and re-places a stop is deferred to Engine (here it just reconciles live positions on restart and cancels orders with no matching position).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_binance_futures_exchange.py  (add)
@pytest.mark.asyncio
async def test_get_positions_uses_exchange_liquidation_price(fx):
    fx._exchange.fetch_positions = AsyncMock(return_value=[
        {"symbol": "BTC/USDT", "side": "long", "entryPrice": 65000.0, "contracts": 0.01,
         "unrealizedPnl": 12.5, "leverage": 5, "liquidationPrice": 58600.0},
        {"symbol": "ETH/USDT", "side": "short", "entryPrice": 3000.0, "contracts": 0.0,  # flat -> skip
         "unrealizedPnl": 0.0, "leverage": 5, "liquidationPrice": None},
    ])
    positions = await fx.get_positions()
    assert len(positions) == 1
    p = positions[0]
    assert p.symbol == "BTC/USDT" and p.side == "LONG"
    assert p.quantity == 0.01 and p.leverage == 5
    assert p.liquidation_price == 58600.0   # exchange truth, not recomputed
    assert p.unrealized_pnl == 12.5

@pytest.mark.asyncio
async def test_get_positions_maps_short(fx):
    fx._exchange.fetch_positions = AsyncMock(return_value=[
        {"symbol": "BTC/USDT", "side": "short", "entryPrice": 65000.0, "contracts": -0.02,
         "unrealizedPnl": -3.0, "leverage": 10, "liquidationPrice": 71000.0},
    ])
    p = (await fx.get_positions())[0]
    assert p.side == "SHORT" and p.quantity == 0.02 and p.liquidation_price == 71000.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_binance_futures_exchange.py -k get_positions -v`
Expected: FAIL — `NotImplementedError`.

- [ ] **Step 3: Implement**

Replace the `get_positions` stub and add `seed_open_positions`:

```python
    async def get_positions(self) -> list[Position]:
        raw = await self._exchange.fetch_positions()
        positions = []
        for p in raw:
            qty = abs(float(p.get("contracts") or 0.0))
            if qty <= 0:
                continue  # flat row — Binance returns a row per symbol even at 0
            liq = p.get("liquidationPrice")
            positions.append(Position(
                symbol=p.get("symbol"),
                side="LONG" if str(p.get("side", "")).lower() == "long" else "SHORT",
                entry_price=float(p.get("entryPrice") or 0.0),
                quantity=qty,
                unrealized_pnl=float(p.get("unrealizedPnl") or 0.0),
                take_profit=None,
                stop_loss=None,
                leverage=int(p.get("leverage") or self.leverage),
                liquidation_price=float(liq) if liq is not None else None,
                mode="FUTURES",
            ))
        return positions

    async def seed_open_positions(self, symbols: list[str]) -> list[Position]:
        """Restart recovery: futures positions are real venue state, so just re-read
        them. Cancel any resting orders on symbols that are now flat (orphaned
        closePosition legs are auto-removed by Binance, but a stale plain order is not)."""
        live = await self.get_positions()
        live_symbols = {p.symbol for p in live}
        for symbol in symbols:
            if symbol in live_symbols:
                continue
            try:
                for o in await self._exchange.fetch_open_orders(symbol):
                    await self.cancel_order(o.get("id"), symbol)
            except Exception:
                pass
        return live
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_binance_futures_exchange.py -v`
Expected: PASS (whole file).

- [ ] **Step 5: Commit**

```bash
git add exchange/binance_futures.py tests/test_binance_futures_exchange.py
git commit -m "feat(futures): get_positions with exchange-truth liquidationPrice + restart reconcile

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# Task 9: Post-open liquidation-buffer enforcement (add margin → close last resort)

**Files:**
- Modify: `exchange/base.py` (default no-op), `exchange/binance_futures.py` (live impl)
- Test: `tests/test_binance_futures_exchange.py` (add)

**Interfaces:**
- Produces: `Exchange.enforce_liquidation_buffer(symbol, current_price, buffer_pct, stop_loss) -> str` — default `"ok"` no-op (paper/spot). Live impl: read the position's real `liquidation_price`; if it is closer to `current_price` than `buffer_pct` AND the stop does not already sit between price and liq, try `add_margin` to push liq away (return `"margin_added"`); only if margin can't be added, market-close reduce-only (return `"closed"`). Returns `"ok"` when no action needed. Consumed by Engine (Task 10).

**Trader rationale (commit note):** never reflex-close on a single tight reading — that chops on fees. Closing is the last resort after add-margin fails.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_binance_futures_exchange.py  (add)
@pytest.mark.asyncio
async def test_enforce_buffer_adds_margin_when_liq_too_close(fx):
    fx._exchange.fetch_positions = AsyncMock(return_value=[
        {"symbol": "BTC/USDT", "side": "long", "entryPrice": 65000.0, "contracts": 0.01,
         "unrealizedPnl": 0.0, "leverage": 20, "liquidationPrice": 64500.0}])  # ~0.77% away
    fx._exchange.add_margin = AsyncMock(return_value={})
    # stop is BELOW liq (64000 < 64500) -> liq is reachable first -> must act
    action = await fx.enforce_liquidation_buffer("BTC/USDT", current_price=65000.0,
                                                 buffer_pct=0.02, stop_loss=64000.0)
    assert action == "margin_added"
    fx._exchange.add_margin.assert_awaited()

@pytest.mark.asyncio
async def test_enforce_buffer_closes_when_margin_fails(fx):
    fx._exchange.fetch_positions = AsyncMock(return_value=[
        {"symbol": "BTC/USDT", "side": "long", "entryPrice": 65000.0, "contracts": 0.01,
         "unrealizedPnl": 0.0, "leverage": 20, "liquidationPrice": 64500.0}])
    fx._exchange.add_margin = AsyncMock(side_effect=Exception("cannot add margin"))
    closes = []
    async def spy(order, **kw):
        closes.append(order); return order
    fx.place_order = spy
    action = await fx.enforce_liquidation_buffer("BTC/USDT", current_price=65000.0,
                                                 buffer_pct=0.02, stop_loss=64000.0)
    assert action == "closed" and closes[0].reduce_only

@pytest.mark.asyncio
async def test_enforce_buffer_noop_when_stop_protects_first(fx):
    # stop (64600) is ABOVE liq (64500): stop fires before liq -> no action
    fx._exchange.fetch_positions = AsyncMock(return_value=[
        {"symbol": "BTC/USDT", "side": "long", "entryPrice": 65000.0, "contracts": 0.01,
         "unrealizedPnl": 0.0, "leverage": 20, "liquidationPrice": 64500.0}])
    fx._exchange.add_margin = AsyncMock()
    action = await fx.enforce_liquidation_buffer("BTC/USDT", current_price=65000.0,
                                                 buffer_pct=0.02, stop_loss=64600.0)
    assert action == "ok"
    fx._exchange.add_margin.assert_not_awaited()

@pytest.mark.asyncio
async def test_enforce_buffer_default_is_noop():
    from exchange.paper_futures import PaperFuturesExchange
    ex = PaperFuturesExchange({"USDT": 1000.0}, leverage=5)
    assert await ex.enforce_liquidation_buffer("BTC/USDT", 100.0, 0.02, 95.0) == "ok"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_binance_futures_exchange.py -k enforce_buffer -v`
Expected: FAIL — `AttributeError: ... 'enforce_liquidation_buffer'`.

- [ ] **Step 3: Implement**

In `exchange/base.py` add the default to `Exchange`:

```python
    async def enforce_liquidation_buffer(self, symbol: str, current_price: float,
                                         buffer_pct: float, stop_loss: float) -> str:
        """Post-open guard. Default no-op ('ok') — paper models liquidation in tick()."""
        return "ok"
```

In `exchange/binance_futures.py` add:

```python
    async def enforce_liquidation_buffer(self, symbol: str, current_price: float,
                                         buffer_pct: float, stop_loss: float) -> str:
        """If the venue's real liquidation price is inside the buffer AND the stop does
        not already trip first, add isolated margin to push liq away (keep the thesis);
        market-close only if margin can't be added. Never reflex-close on one reading."""
        pos = next((p for p in await self.get_positions() if p.symbol == symbol), None)
        if pos is None or pos.liquidation_price is None or current_price <= 0:
            return "ok"
        liq = pos.liquidation_price
        dist = abs(current_price - liq) / current_price
        if dist >= buffer_pct:
            return "ok"
        # If the stop fires before liq is reached, the stop protects us — do nothing.
        stop_protects = (pos.side == "LONG" and stop_loss > liq) or \
                        (pos.side == "SHORT" and stop_loss < liq)
        if stop_protects:
            return "ok"
        # Add margin sized to roughly double the current isolated margin (push liq away).
        try:
            margin = (pos.entry_price * pos.quantity) / max(1, pos.leverage)
            await self._exchange.add_margin(symbol, round(margin, 2))
            return "margin_added"
        except Exception:
            close = Order(id=f"liqguard-{symbol}", symbol=symbol,
                          side="SELL" if pos.side == "LONG" else "BUY", type="MARKET",
                          quantity=pos.quantity, price=None, status="PENDING",
                          exchange_order_id=None, reduce_only=True)
            await self.place_order(close, current_price=current_price)
            return "closed"
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_binance_futures_exchange.py -k enforce_buffer -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add exchange/base.py exchange/binance_futures.py tests/test_binance_futures_exchange.py
git commit -m "feat(futures): post-open liq-buffer guard adds margin, closes only as last resort

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# Task 10: Engine wiring — funding before evaluate, liq-buffer after open

**Files:**
- Modify: `core/engine.py`
- Test: `tests/test_engine.py` (add — reuse the file's existing fake-exchange/strategy fixtures)

**Interfaces:**
- Consumes: `exchange.fetch_funding_rate`, `exchange.enforce_liquidation_buffer`, `RiskManager.evaluate(..., funding_rate=, funding_threshold=)`.
- Produces: Engine, when `self.market == "futures"`, fetches funding before calling `risk.evaluate` and passes `funding_rate` + `self.funding_skip_threshold`; after a successful futures open + protect, calls `enforce_liquidation_buffer`. New Engine kwarg `funding_skip_threshold: float = 0.001`. Spot path unchanged (no funding fetch, no buffer call).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_engine.py  (add — match this file's existing make_engine/fake-exchange helpers)
# 1. test_engine_fetches_funding_and_passes_to_risk:
#    market="futures"; stub exchange.fetch_funding_rate -> 0.0012; feed a BUY signal;
#    assert risk_manager.evaluate received funding_rate=0.0012 (spy/capture kwargs)
#    and the order was rejected (funding_adverse) so no position opened.
# 2. test_engine_calls_liq_buffer_after_open:
#    market="futures"; funding 0.0; a BUY that passes risk; stub
#    exchange.enforce_liquidation_buffer as a spy; assert it was awaited once with
#    the symbol after the open+protect.
# 3. test_spot_engine_does_not_fetch_funding:
#    market="spot"; spy fetch_funding_rate; feed a BUY; assert fetch_funding_rate
#    was NOT awaited and enforce_liquidation_buffer was NOT awaited.
```

Write these three concretely against the existing `tests/test_engine.py` harness (it already builds an Engine with a stub strategy + a fake/paper exchange and feeds candles — reuse that exact shape; add `AsyncMock` spies for `fetch_funding_rate` and `enforce_liquidation_buffer`).

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_engine.py -k "funding or liq_buffer" -v`
Expected: FAIL (funding not threaded; buffer not called).

- [ ] **Step 3: Implement**

In `core/engine.py` `__init__`, add `funding_skip_threshold: float = 0.001` and store `self.funding_skip_threshold = funding_skip_threshold`.

At the point where the engine calls `self.risk_manager.evaluate(...)` for a futures market, fetch funding first and pass it through. Locate the existing `evaluate(` call and extend the futures branch:

```python
        funding_rate = 0.0
        if self.market == "futures":
            try:
                funding_rate = await self.exchange.fetch_funding_rate(self.symbol)
            except Exception:
                funding_rate = 0.0  # fail-open on the data fetch; gate just won't trip
        order = self.risk_manager.evaluate(
            signal, balance, positions,
            market=self.market, leverage=self.leverage,
            risk_per_trade=self.risk_per_trade,
            funding_rate=funding_rate,
            funding_threshold=self.funding_skip_threshold,
            # ... keep any existing kwargs already passed here (liq_buffer_pct etc.)
        )
```

After a successful futures open and its `protect_position`, add the buffer enforcement (use the candle's close as `current_price`):

```python
        if self.market == "futures" and order is not None:
            try:
                action = await self.exchange.enforce_liquidation_buffer(
                    self.symbol, current_price=close_price,
                    buffer_pct=self._liq_buffer_pct, stop_loss=signal.stop_loss,
                )
                if action in ("margin_added", "closed"):
                    self.logger.warning(f"liq-buffer guard on {self.symbol}: {action}")
            except Exception as exc:
                self.logger.warning(f"liq-buffer guard failed on {self.symbol}: {exc}")
```

Use whatever the engine already calls the per-evaluation close price and its liq-buffer field; if the engine has no `_liq_buffer_pct` yet, default the call's `buffer_pct=0.0` from a new `__init__` kwarg `liq_buffer_pct: float = 0.0` (thread the same value into `evaluate`).

- [ ] **Step 4: Run to verify pass + no spot regression**

Run: `.venv/bin/python -m pytest tests/test_engine.py -q`
Expected: PASS (existing engine tests + the three new ones).

- [ ] **Step 5: Commit**

```bash
git add core/engine.py tests/test_engine.py
git commit -m "feat(engine): thread funding into risk + enforce liq-buffer after futures open

Old: engine evaluated futures signals without funding context and never re-checked
the real liquidation price after opening.
New: futures path fetches funding_rate before evaluate (spot path unchanged — no
fetch) and calls enforce_liquidation_buffer post-open. Both are futures-gated.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# Task 11: Config + main.py per-(market,network) exchange isolation

**Files:**
- Modify: `core/strategy_runtime.py`, `core/loop_config.py`
- Modify: `main.py`
- Test: `tests/test_loop_config.py` (add), `tests/test_main_wiring.py` (add)

**Interfaces:**
- Consumes: `BinanceFuturesExchange`, the engine kwargs from Task 10.
- Produces: per-loop `funding_skip_threshold: float = 0.001` field + `FUNDING_SKIP_THRESHOLD` env parse. `main.py` builds a `BinanceFuturesExchange` for futures loops on a live network (one instance per (market, network); spot loops keep the shared `BinanceExchange`), and threads the futures engine kwargs (`market/leverage/risk_per_trade/max_hold_hours/reentry_cooldown_bars/funding_skip_threshold/liq_buffer_pct`) in LIVE mode too — not only paper.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_loop_config.py  (add)
def test_funding_skip_threshold_defaults(monkeypatch):
    # no env -> default 0.001
    cfg = parse_one_loop(env={"LOOP1_STRATEGY": "supertrend", "LOOP1_MARKET": "futures",
                              "LOOP1_LEVERAGE": "5"}, prefix="LOOP1_")  # match this file's helper
    assert cfg.funding_skip_threshold == 0.001

def test_funding_skip_threshold_parsed(monkeypatch):
    cfg = parse_one_loop(env={"LOOP1_STRATEGY": "supertrend", "LOOP1_MARKET": "futures",
                              "LOOP1_LEVERAGE": "5", "LOOP1_FUNDING_SKIP_THRESHOLD": "0.002"},
                         prefix="LOOP1_")
    assert cfg.funding_skip_threshold == 0.002
```

```python
# tests/test_main_wiring.py  (add)
def test_live_futures_loop_builds_binance_futures_exchange(monkeypatch):
    # Build the live per-loop exchange factory for a futures loop on a live network and
    # assert it returns a BinanceFuturesExchange (spot loop -> shared BinanceExchange).
    # Use the same factory main.py exposes for live wiring (mirror Task 11's _build_live_exchange_for).
    ...
```

Write `test_main_wiring.py` concretely against the new `main._build_live_exchange_for(cfg, settings, spot_exchange)` factory introduced below (patch `main.BinanceFuturesExchange` with a sentinel and assert type selection by `cfg.market`).

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_loop_config.py tests/test_main_wiring.py -k "funding or live_futures" -v`
Expected: FAIL — field/factory missing.

- [ ] **Step 3: Implement config**

In `core/strategy_runtime.py`, add to the dataclass: `funding_skip_threshold: float = 0.001`.
In `core/loop_config.py`, parse it (near the other futures fields) and pass to the constructor:

```python
        funding_skip_threshold = float(lp.get("FUNDING_SKIP_THRESHOLD",
                                              env.get("FUNDING_SKIP_THRESHOLD", "0.001")))
```
Add `funding_skip_threshold=funding_skip_threshold` to both the default block (line ~135) and the parsed block (line ~178).

- [ ] **Step 4: Implement main.py wiring**

Add a live factory mirroring `_build_paper_exchange_for`:

```python
def _build_live_exchange_for(cfg, settings, spot_exchange):
    """Live per-loop exchange: a futures loop gets a BinanceFuturesExchange; spot loops
    share the one BinanceExchange. ponytail: cache one futures client per leverage via
    the caller — this just selects the type."""
    if getattr(cfg, "market", "spot") == "futures":
        return BinanceFuturesExchange(
            api_key=settings.binance_api_key,
            api_secret=settings.binance_api_secret,
            testnet=settings.binance_testnet,
            leverage=getattr(cfg, "leverage", 1),
        )
    return spot_exchange
```

Import it: `from exchange.binance_futures import BinanceFuturesExchange`.

Replace the per-loop exchange assignment (currently lines ~230-236) so live also isolates:

```python
        for spec in loop_specs:
            spec.exchange = (
                _build_paper_exchange_for(spec.config, {"USDT": 10000.0})
                if paper_mode
                else _build_live_exchange_for(spec.config, settings, exchange)
            )
```

Extend the engine-kwargs gate (line ~269) to LIVE futures too, and add the two new kwargs:

```python
                if spec.config.market == "futures":
                    engine_kwargs = {
                        "market": spec.config.market,
                        "leverage": spec.config.leverage,
                        "risk_per_trade": spec.config.risk_per_trade,
                        "max_hold_hours": spec.config.max_hold_hours,
                        "reentry_cooldown_bars": spec.config.reentry_cooldown_bars,
                        "funding_skip_threshold": spec.config.funding_skip_threshold,
                        "liq_buffer_pct": float(os.getenv("LIQ_BUFFER_PCT", "0.0")),
                    }
```

(Remove the `paper_mode and` condition so the kwargs apply in LIVE futures as well.)

- [ ] **Step 5: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/test_loop_config.py tests/test_main_wiring.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add core/strategy_runtime.py core/loop_config.py main.py tests/test_loop_config.py tests/test_main_wiring.py
git commit -m "feat: per-(market,network) live exchange isolation + funding_skip_threshold config

Old: all live loops shared one spot BinanceExchange; futures engine kwargs were
paper-only.
New: futures loops on a live network get a BinanceFuturesExchange; spot loops keep the
shared spot client. Futures engine kwargs (incl. funding_skip_threshold, liq_buffer_pct)
now thread in LIVE too. Spot wiring unchanged.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# Task 12: §9 supertrend short re-validation on the futures bench

**Files:**
- Create: `analysis/select_strategy_futures.py`
- Test: `tests/test_select_strategy_futures.py`

**Interfaces:**
- Consumes: existing `analysis/select_strategy.py` (`rank_results`, `select_strategy`, `load_candles`, `slice_last_days`) and `PaperFuturesExchange`.
- Produces: `select_strategy_futures(symbols, days=60, ...)` — re-runs the §9 selection driving signals through a `market="futures"` `PaperFuturesExchange` so SELL signals open shorts (the spot harness dropped them). Emits a data verdict (ranked rows + whether `supertrend`'s short side clears the `min_trades`/`max_dd` filters). Read-only analysis; no live calls.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_select_strategy_futures.py
def test_futures_selection_routes_sell_signals_as_shorts():
    # On a synthetic down-trend candle series, supertrend emits SELL signals; the
    # futures bench must record SHORT trades (count > 0), proving SELL is no longer
    # dropped as it was on the spot harness.
    from analysis.select_strategy_futures import run_single_strategy_futures
    candles = _synthetic_downtrend()  # helper: monotonic-ish down series, enough bars
    result = run_single_strategy_futures("supertrend", candles, leverage=3)
    assert result["total_trades"] > 0
    assert result["short_trades"] > 0   # the whole point: shorts now execute

def test_rank_results_reused_unchanged():
    # the ranking/filtering is the same §9 function, not a fork
    from analysis.select_strategy_futures import rank_results as f_rank
    from analysis.select_strategy import rank_results as s_rank
    assert f_rank is s_rank
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_select_strategy_futures.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

```python
# analysis/select_strategy_futures.py
"""Re-run §9 strategy selection on the FUTURES paper bench so SELL signals open shorts.

ponytail: thin wrapper over analysis/select_strategy.py — reuses its ranking/filtering
and candle loading verbatim; only the execution exchange differs (PaperFuturesExchange
instead of the spot PaperExchange), which is the one thing that made the spot run drop
short signals."""
from analysis.select_strategy import rank_results, load_candles, slice_last_days  # noqa: F401
from exchange.paper_futures import PaperFuturesExchange
from core.strategy_registry import StrategyRegistry


def run_single_strategy_futures(name: str, candles, *, leverage: int = 3,
                                initial_balance: float = 1000.0) -> dict:
    """Drive one strategy's signals through a futures paper exchange over `candles`.
    Returns the same row shape §9 ranks on, plus short_trades for the verdict."""
    strategy = StrategyRegistry().build(name, lambda k, d: d)
    ex = PaperFuturesExchange({"USDT": initial_balance}, leverage=leverage)
    # ... feed candles through the same evaluate→order→tick loop the spot bench uses,
    # but on `ex`; tally realized TradeRecords. Reuse the spot bench's per-bar driver if
    # analysis/select_strategy.py exposes one; otherwise replicate its minimal loop here.
    short_trades = ...  # count TradeRecords whose entry side opened a SHORT
    return {"strategy": name, "total_trades": ..., "short_trades": short_trades,
            "total_pnl": ..., "sharpe_ratio": ..., "max_drawdown": ...}


def select_strategy_futures(symbols, days: int = 60, *, leverage: int = 3,
                            min_trades: int = 30, max_dd: float = 0.10) -> dict:
    rows = []
    for sym in symbols:
        candles = slice_last_days(load_candles(sym), days)
        for name in ("supertrend",):  # the only bidirectional candidate today
            rows.append(run_single_strategy_futures(name, candles, leverage=leverage))
    ranked = rank_results(rows, min_trades=min_trades, max_dd=max_dd)
    return {"ranked": ranked,
            "supertrend_short_validated": any(r["strategy"] == "supertrend" and r["short_trades"] > 0
                                              for r in ranked)}
```

The implementer wires the per-bar driver concretely to whatever `analysis/select_strategy.py` already exposes (read that file; if it has a reusable single-strategy runner, call it with the futures exchange; if not, lift its minimal evaluate→tick loop). Keep ranking/loading imported, not reimplemented.

- [ ] **Step 4: Run to verify it passes + produce the verdict**

Run: `.venv/bin/python -m pytest tests/test_select_strategy_futures.py -v`
Then run the selection on the real 60-day data and record the verdict in the commit body:
Run: `.venv/bin/python -c "from analysis.select_strategy_futures import select_strategy_futures; import json; print(json.dumps(select_strategy_futures(['BTC/USDT','ETH/USDT']), default=str))"`
Expected: PASS; verdict printed (whether supertrend's short side clears the filters).

- [ ] **Step 5: Commit**

```bash
git add analysis/select_strategy_futures.py tests/test_select_strategy_futures.py
git commit -m "feat(analysis): §9 supertrend short re-validation on futures bench

Re-runs §9 selection through PaperFuturesExchange so SELL signals open shorts (the
spot harness dropped them). DATA VERDICT: <paste the printed short-validation result>.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# Task 13: Futures-testnet contract test (opt-in)

**Files:**
- Create: `tests/test_contract_binance_futures_testnet.py`

**Interfaces:**
- Consumes: the full `BinanceFuturesExchange`. Network test; skipped unless `RUN_CONTRACT_TESTS=1`. Mirrors `tests/test_contract_binance_testnet.py`'s philosophy — only a real call catches "this ccxt method/param no longer exists on the futures venue".

- [ ] **Step 1: Write the contract test**

```python
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
```

- [ ] **Step 2: Verify it is skipped by default**

Run: `.venv/bin/python -m pytest tests/test_contract_binance_futures_testnet.py -v`
Expected: SKIPPED (RUN_CONTRACT_TESTS unset) — the default-suite must stay green/offline.

- [ ] **Step 3: (User-run, gated) Execute against real testnet**

Run (user, with testnet keys in `.env`): `RUN_CONTRACT_TESTS=1 .venv/bin/python -m pytest tests/test_contract_binance_futures_testnet.py -v`
Expected: PASS — real open → protect → `liquidationPrice` reported → close. **This is the M2 gate.**

- [ ] **Step 4: Commit**

```bash
git add tests/test_contract_binance_futures_testnet.py
git commit -m "test: opt-in Binance USDT-M futures testnet contract test (M2 gate)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## M2 Exit Gate

- [ ] Full offline suite green: `.venv/bin/python -m pytest -q` (no network; contract tests skipped).
- [ ] Spot path unchanged — `tests/test_binance_exchange.py`, `tests/test_paper_exchange*.py` pass untouched.
- [ ] **User runs** the futures-testnet contract test with real testnet keys: `RUN_CONTRACT_TESTS=1 ... test_contract_binance_futures_testnet.py` → green.
- [ ] **User runs** a supervised testnet session (a few candles, real futures loop) and confirms: positions reconcile via `fetch_positions`, `liquidation_price` is populated from the venue, the funding skip surfaces in Telegram when triggered, and the liq-buffer guard fires (add-margin) on a deliberately high-leverage tight setup.
- [ ] §9 futures verdict recorded (Task 12 commit body): does supertrend's short side clear `min_trades`/`max_dd`.

---

## Self-Review notes

- **Spec coverage (this plan):** spec §M2 bullets → tasks: adapter (init/data/balance/funding) Task 4; leverage/isolated race guard Task 5; market open + reduce-only + min-notional + -2022 Task 6; closePosition MARK brackets + stop-first Task 7; get_positions exchange-truth liq + reconcile Task 8; post-open add-margin/close guard Task 9; funding ABC hook Task 2 + skip gate Task 3; mmr constant Task 1; engine threading Task 10; per-(market,network) wiring + config Task 11; §9 short re-validation Task 12; contract test Task 13. M3/§10/§11 remain follow-on plans (out of scope).
- **Placeholders:** Task 10's three engine tests and Task 12's per-bar driver are described against existing harness code (`tests/test_engine.py` fixtures; `analysis/select_strategy.py` internals) rather than reproduced verbatim, because they must reuse those files' exact shapes — the implementer reads the file and writes them concretely from the named behaviors. Task 11's `test_main_wiring` body is specified against the new `_build_live_exchange_for` factory it introduces. All other code/test steps are concrete.
- **Type consistency:** `fetch_funding_rate(symbol)->float`, `evaluate(..., funding_rate=, funding_threshold=)`, `enforce_liquidation_buffer(symbol, current_price, buffer_pct, stop_loss)->str` ("ok"/"margin_added"/"closed"), `MMR_DEFAULT`, `Position(leverage=, liquidation_price=, mode="FUTURES")`, `Order(reduce_only=)`, `BinanceFuturesExchange(api_key, api_secret, testnet, leverage)`, `_build_live_exchange_for(cfg, settings, spot_exchange)`, `funding_skip_threshold` — used consistently across tasks.
- **Trader consult folded in:** closePosition brackets (T7), filled-qty/min-notional (T6), stop-first never-naked (T7), MARK price (T7), add-margin-not-panic-close (T9), leverage tiers note + race guard (T5), -2022 benign (T6), reconciliation (T8). Funding kept as a binary skip at the **raised** 0.1%/8h threshold per the user's decision; per-trade expected-funding-vs-EV gating deferred (a §10/M3 refinement, noted here).
