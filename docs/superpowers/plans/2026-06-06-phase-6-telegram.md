# Phase 6: Telegram Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Telegram bot that sends trade alerts (BUY/SELL/warning) and handles commands (/status, /pause, /resume, /pnl, /close). Bot is decoupled from Engine via a simple callback interface so it can be used in both live and paper trading modes.

**Architecture:** `notifier/telegram.py` owns all bot logic. Engine calls `notifier.on_signal()` and `notifier.on_order_filled()` — it does not import from `telegram` library directly. `BotController` receives commands and delegates to an `EngineController` interface. Tests mock the Telegram API entirely.

**Tech Stack:** python-telegram-bot 21+, asyncio. Add to `pyproject.toml`.

---

## File Map

| File | Responsibility |
|---|---|
| `pyproject.toml` | **Modified** — add python-telegram-bot |
| `notifier/telegram.py` | `TelegramNotifier` — send alerts + handle commands |
| `notifier/engine_controller.py` | Abstract `EngineController` interface (pause/resume/close) |
| `tests/test_telegram.py` | Alert formatting + command handling tests |

---

## Task 1: Add Dependency

- [ ] **Step 1: Add `python-telegram-bot` to `pyproject.toml`**

In `[project] dependencies`, append:

```toml
"python-telegram-bot>=21.0",
```

- [ ] **Step 2: Install**

```bash
pip install -e ".[dev]"
```

Expected: installs without errors.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add python-telegram-bot dependency"
```

---

## Task 2: Engine Controller Interface

**Files:**
- Create: `notifier/engine_controller.py`

No tests for this task — it's an abstract interface.

- [ ] **Step 1: Implement `notifier/engine_controller.py`**

```python
# notifier/engine_controller.py
from abc import ABC, abstractmethod


class EngineController(ABC):

    @abstractmethod
    async def pause(self) -> None:
        """Stop the trading loop from placing new orders."""

    @abstractmethod
    async def resume(self) -> None:
        """Resume the trading loop."""

    @abstractmethod
    async def get_status(self) -> dict:
        """Return dict with keys: running (bool), open_positions (list), strategy_id (str)."""

    @abstractmethod
    async def get_pnl(self) -> dict:
        """Return dict with keys: daily (float), total (float)."""

    @abstractmethod
    async def close_position(self, symbol: str) -> bool:
        """Force-close open position for symbol. Return True if closed, False if not found."""
```

- [ ] **Step 2: Commit**

```bash
git add notifier/engine_controller.py
git commit -m "feat: EngineController abstract interface for Telegram commands"
```

---

## Task 3: Telegram Notifier

**Files:**
- Create: `notifier/telegram.py`
- Create: `tests/test_telegram.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_telegram.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from core.models import Signal, Order
from notifier.telegram import TelegramNotifier, format_signal_alert, format_order_alert


# ── Formatting tests (no Telegram API needed) ───────────────────────────────

def test_format_buy_signal_alert():
    signal = Signal(
        symbol="BTC/USDT", side="BUY", entry_price=65230.0,
        take_profit=67000.0, stop_loss=63500.0,
        trailing_sl=False, confidence=0.88,
        strategy_id="rsi_macd", timestamp=datetime.utcnow(),
    )
    text = format_signal_alert(signal)
    assert "BUY" in text
    assert "BTC/USDT" in text
    assert "65,230" in text
    assert "67,000" in text
    assert "63,500" in text


def test_format_sell_signal_alert():
    signal = Signal(
        symbol="ETH/USDT", side="SELL", entry_price=3500.0,
        take_profit=3300.0, stop_loss=3600.0,
        trailing_sl=False, confidence=0.75,
        strategy_id="rsi_macd", timestamp=datetime.utcnow(),
    )
    text = format_signal_alert(signal)
    assert "SELL" in text
    assert "ETH/USDT" in text


def test_format_order_alert_profit():
    order = Order(
        id="ord-001", symbol="BTC/USDT", side="SELL",
        type="MARKET", quantity=0.01, price=67100.0,
        status="FILLED", exchange_order_id="ex-001",
    )
    text = format_order_alert(order, entry_price=65230.0, realized_pnl=18.7)
    assert "67,100" in text
    assert "18.7" in text or "+$18" in text


def test_format_order_alert_loss():
    order = Order(
        id="ord-002", symbol="BTC/USDT", side="SELL",
        type="MARKET", quantity=0.01, price=63500.0,
        status="FILLED", exchange_order_id="ex-002",
    )
    text = format_order_alert(order, entry_price=65230.0, realized_pnl=-17.3)
    assert "-" in text or "loss" in text.lower()


# ── Command parsing tests (mock bot and controller) ──────────────────────────

@pytest.fixture
def mock_controller():
    ctrl = AsyncMock()
    ctrl.get_status.return_value = {
        "running": True,
        "open_positions": [{"symbol": "BTC/USDT", "quantity": 0.01, "unrealized_pnl": 50.0}],
        "strategy_id": "rsi_macd",
    }
    ctrl.get_pnl.return_value = {"daily": 182.0, "total": 1540.0}
    ctrl.close_position.return_value = True
    return ctrl


@pytest.mark.asyncio
async def test_handle_status_command(mock_controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=mock_controller)
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    await notifier.cmd_status(update, None)
    update.message.reply_text.assert_called_once()
    call_text = update.message.reply_text.call_args[0][0]
    assert "BTC/USDT" in call_text or "rsi_macd" in call_text


@pytest.mark.asyncio
async def test_handle_pause_command(mock_controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=mock_controller)
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    await notifier.cmd_pause(update, None)
    mock_controller.pause.assert_awaited_once()
    update.message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_handle_resume_command(mock_controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=mock_controller)
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    await notifier.cmd_resume(update, None)
    mock_controller.resume.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_pnl_command(mock_controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=mock_controller)
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    await notifier.cmd_pnl(update, None)
    call_text = update.message.reply_text.call_args[0][0]
    assert "182" in call_text
    assert "1,540" in call_text or "1540" in call_text


@pytest.mark.asyncio
async def test_handle_close_command(mock_controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=mock_controller)
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ["BTC"]
    await notifier.cmd_close(update, context)
    mock_controller.close_position.assert_awaited_once_with("BTC")
    call_text = update.message.reply_text.call_args[0][0]
    assert "closed" in call_text.lower() or "BTC" in call_text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_telegram.py -v
```

Expected: `ModuleNotFoundError: No module named 'notifier.telegram'`

- [ ] **Step 3: Implement `notifier/telegram.py`**

```python
# notifier/telegram.py
from core.models import Order, Signal
from notifier.engine_controller import EngineController


def format_signal_alert(signal: Signal) -> str:
    emoji = "🟢" if signal.side == "BUY" else "🔴"
    tp = f"{signal.take_profit:,.0f}" if signal.take_profit else "—"
    sl = f"{signal.stop_loss:,.0f}" if signal.stop_loss else "—"
    return (
        f"{emoji} {signal.side}  {signal.symbol} @ {signal.entry_price:,.0f}\n"
        f"TP: {tp}  |  SL: {sl}\n"
        f"Confidence: {signal.confidence:.0%}  |  Strategy: {signal.strategy_id}"
    )


def format_order_alert(order: Order, entry_price: float, realized_pnl: float) -> str:
    emoji = "🟢" if realized_pnl >= 0 else "🔴"
    sign = "+" if realized_pnl >= 0 else ""
    pct = ((order.price - entry_price) / entry_price * 100) if entry_price else 0
    return (
        f"{emoji} FILLED  {order.symbol} @ {order.price:,.0f}\n"
        f"PnL: {sign}${realized_pnl:.2f} ({sign}{pct:.1f}%)"
    )


class TelegramNotifier:

    def __init__(self, token: str, chat_id: str, controller: EngineController):
        self._token = token
        self._chat_id = chat_id
        self._controller = controller
        self._app = None  # initialized in start()

    async def send(self, text: str) -> None:
        if self._app is None:
            return
        await self._app.bot.send_message(chat_id=self._chat_id, text=text)

    async def on_signal(self, signal: Signal) -> None:
        if signal.side != "HOLD":
            await self.send(format_signal_alert(signal))

    async def on_order_filled(self, order: Order, entry_price: float, realized_pnl: float) -> None:
        await self.send(format_order_alert(order, entry_price, realized_pnl))

    async def on_daily_limit_hit(self) -> None:
        await self.send("⚠️ Daily loss limit reached — bot paused")

    # ── Command handlers ──────────────────────────────────────────────────

    async def cmd_status(self, update, context) -> None:
        status = await self._controller.get_status()
        positions = status.get("open_positions", [])
        pos_text = "\n".join(
            f"  • {p['symbol']}  qty={p['quantity']}  unrealised=${p['unrealized_pnl']:.2f}"
            for p in positions
        ) or "  None"
        text = (
            f"{'🟢 Running' if status['running'] else '⏸ Paused'}\n"
            f"Strategy: {status['strategy_id']}\n"
            f"Open positions:\n{pos_text}"
        )
        await update.message.reply_text(text)

    async def cmd_pause(self, update, context) -> None:
        await self._controller.pause()
        await update.message.reply_text("⏸ Bot paused — no new orders will be placed.")

    async def cmd_resume(self, update, context) -> None:
        await self._controller.resume()
        await update.message.reply_text("▶️ Bot resumed.")

    async def cmd_pnl(self, update, context) -> None:
        pnl = await self._controller.get_pnl()
        await update.message.reply_text(
            f"📊 P&L\n"
            f"Daily:  ${pnl['daily']:,.2f}\n"
            f"Total:  ${pnl['total']:,.2f}"
        )

    async def cmd_close(self, update, context) -> None:
        if not context.args:
            await update.message.reply_text("Usage: /close <symbol>  e.g. /close BTC")
            return
        symbol = context.args[0].upper()
        closed = await self._controller.close_position(symbol)
        if closed:
            await update.message.reply_text(f"✅ {symbol} position closed.")
        else:
            await update.message.reply_text(f"⚠️ No open position for {symbol}.")

    async def start(self) -> None:
        """Build and start the Telegram Application. Call once at bot startup."""
        from telegram.ext import Application, CommandHandler
        self._app = Application.builder().token(self._token).build()
        self._app.add_handler(CommandHandler("status", self.cmd_status))
        self._app.add_handler(CommandHandler("pause", self.cmd_pause))
        self._app.add_handler(CommandHandler("resume", self.cmd_resume))
        self._app.add_handler(CommandHandler("pnl", self.cmd_pnl))
        self._app.add_handler(CommandHandler("close", self.cmd_close))
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()

    async def stop(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_telegram.py -v
```

Expected: 11 PASSED

- [ ] **Step 5: Run full suite**

```bash
pytest -v --tb=short
```

Expected: all PASSED

- [ ] **Step 6: Commit**

```bash
git add notifier/telegram.py notifier/engine_controller.py tests/test_telegram.py
git commit -m "feat: TelegramNotifier with alerts and /status /pause /resume /pnl /close commands"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** BUY/SELL alerts ✓, daily loss limit warning ✓, /status ✓, /pause ✓, /resume ✓, /pnl ✓, /close <symbol> ✓
- [x] **No placeholders:** all handlers fully implemented
- [x] **Decoupling:** `TelegramNotifier` depends on `EngineController` abstract interface, not on concrete `Engine`. Engine wires the notifier callbacks in Plan 7.
- [x] **Format helpers are pure functions:** `format_signal_alert` and `format_order_alert` are standalone functions — easy to test without mocking Telegram

---

## Next Plan

**Plan 7:** Binance Live Integration — `exchange/binance.py` implementing the `Exchange` interface, OCO order execution, WebSocket market data feed, main entry point wiring everything together.
