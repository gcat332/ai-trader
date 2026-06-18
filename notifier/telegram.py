# notifier/telegram.py
import asyncio
import contextlib
import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from core.models import Order, Signal
from notifier.engine_controller import EngineController

logger = logging.getLogger("notifier.telegram")
THAI_TZ = ZoneInfo("Asia/Bangkok")


def _as_thai_time(value: datetime | None = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(THAI_TZ)


def _thai_datetime(value: datetime | None = None) -> str:
    return _as_thai_time(value).strftime("%d %b %Y %H:%M ICT")


def _thai_time(value: datetime | None = None) -> str:
    return _as_thai_time(value).strftime("%H:%M ICT")


def _display_date(day: str | None) -> str:
    if not day:
        return _as_thai_time().strftime("%d %b %Y")
    try:
        return datetime.fromisoformat(day).strftime("%d %b %Y")
    except ValueError:
        return day


def format_signal_alert(signal: Signal) -> str:
    emoji = "🟢" if signal.side == "BUY" else "🔴"
    tp = f"{signal.take_profit:,.0f}" if signal.take_profit else "—"
    sl = f"{signal.stop_loss:,.0f}" if signal.stop_loss else "—"
    text = (
        f"{emoji} Signal · {signal.strategy_id}\n"
        f"{_thai_datetime(signal.timestamp)}\n\n"
        f"{signal.side} {signal.symbol} @ {signal.entry_price:,.0f}\n"
        f"TP: {tp}  |  SL: {sl}\n"
        f"Confidence: {signal.confidence:.0%}"
    )
    if signal.narrative:
        # Add abbreviated narrative (first 2 parts only to keep message short)
        short = " | ".join(signal.narrative.split(" | ")[:2])
        text += f"\n{short}"
    return text


def _money(v: float) -> str:
    return f"{'+' if v >= 0 else '-'}${abs(v):,.2f}"


def format_daily_summary(
    total_evaluated: int,
    placed: int,
    rejected: int,
    hold: int,
    rejection_breakdown: dict[str, int],
    day: str | None = None,
    *,
    day_pnl: float | None = None,
    total_pnl: float | None = None,
    wins: int | None = None,
    trades: int | None = None,
    balance: float | None = None,
    trade_rows: list[dict] | None = None,
    generated_at: datetime | None = None,
    open_order_count: int | None = None,
    open_position_count: int | None = None,
) -> str:
    lines = [
        f"📅 Daily Summary · {_display_date(day)}",
        f"Generated: {_thai_time(generated_at)}",
        "",
    ]
    if trades is not None:
        lines.append(f"Trades: {trades}")
    if day_pnl is not None:
        lines.append(f"PnL: {_money(day_pnl)}")
    if trades is not None:
        win_rate = (wins / trades) if trades else 0.0
        lines.append(f"Win rate: {win_rate:.0%} ({wins or 0}/{trades} trades)")
    if open_order_count is not None:
        lines.append(f"Open orders: {open_order_count}")
    if open_position_count is not None:
        lines.append(f"Open positions: {open_position_count}")
    if trade_rows:
        by_strategy: dict[str, dict[str, float | int]] = {}
        for trade in trade_rows:
            strategy_id = trade.get("strategy_id") or "unknown"
            pnl = trade.get("realized_pnl") or 0.0
            row = by_strategy.setdefault(strategy_id, {"pnl": 0.0, "wins": 0, "trades": 0})
            row["pnl"] = float(row["pnl"]) + pnl
            row["trades"] = int(row["trades"]) + 1
            if pnl > 0:
                row["wins"] = int(row["wins"]) + 1
        lines.extend(["", "Strategies"])
        for strategy_id, row in sorted(by_strategy.items()):
            lines.append(f"  • {strategy_id}: {_money(float(row['pnl']))}")
    return "\n".join(lines)


def format_weekly_summary(trades: list[dict]) -> str:
    total_pnl = sum((t.get("realized_pnl") or 0) for t in trades)
    wins = sum(1 for t in trades if (t.get("realized_pnl") or 0) > 0)
    win_rate = (wins / len(trades)) if trades else 0.0
    by_strategy: dict[str, float] = {}
    for trade in trades:
        strategy_id = trade.get("strategy_id") or "unknown"
        by_strategy[strategy_id] = by_strategy.get(strategy_id, 0.0) + (trade.get("realized_pnl") or 0)

    lines = [
        "Weekly Summary",
        f"Trades: {len(trades)}",
        f"PnL: {_money(total_pnl)}",
        f"Win rate: {win_rate:.0%} ({wins}/{len(trades)} trades)",
    ]
    if by_strategy:
        lines.append("Strategies:")
        for strategy_id, pnl in sorted(by_strategy.items()):
            lines.append(f"  • {strategy_id}: {_money(pnl)}")
    return "\n".join(lines)


def format_order_alert(order: Order, entry_price: float, realized_pnl: float) -> str:
    emoji = "🟢" if realized_pnl >= 0 else "🔴"
    sign = "+" if realized_pnl >= 0 else ""
    pct = ((order.price - entry_price) / entry_price * 100) if entry_price else 0
    return (
        f"{emoji} Order Filled · {order.strategy_id or 'unknown'}\n"
        f"{_thai_datetime()}\n\n"
        f"{order.symbol} {order.side} @ {order.price:,.0f}\n"
        f"PnL: {sign}${realized_pnl:.2f} ({sign}{pct:.1f}%)"
    )


def format_drift_alert(event: "DriftEvent") -> str:
    return (
        f"⚠️ Strategy Drift Detected\n"
        f"Win rate (last 30): {event.win_rate_30:.1%}  |  "
        f"Calibration: {event.calibration_score:.2f}\n"
        f"Reason: {event.reason}\n"
        f"Retraining model now..."
    )


def format_retrain_complete(holdout_accuracy: float, model_id: str) -> str:
    return (
        f"🔄 Model Retrain Complete\n"
        f"Model ID: {model_id}\n"
        f"Holdout accuracy: {holdout_accuracy:.1%}\n"
        f"Running A/B test (shadow mode)..."
    )


def format_strategy_switch(sw) -> str:
    emoji = {"SWAP": "🔀", "RETRAIN": "🔧", "EXPLORE": "🧭", "HOLD_COURSE": "⏸"}.get(sw.decision, "ℹ️")
    return (f"{emoji} Strategy {sw.decision} [{sw.regime}]\n"
            f"{sw.from_strategy} → {sw.to_strategy}\n{sw.reason}")


def format_strategy_list(strategies: list[dict]) -> str:
    lines = ["Strategies"]
    for s in strategies:
        running = bool(s.get("running"))
        state = "running" if running else "stopped"
        state_icon = "🟢" if running else "⏸"
        alloc = s.get("allocation_pct")
        alloc_text = f"{alloc:.0%}" if isinstance(alloc, float) else "unset"
        positions = s.get("open_positions") or []
        open_order_count = int(s.get("open_order_count") or len(s.get("open_orders") or []))
        lines.extend([
            "",
            f"{state_icon} {s['loop_id']} / {s['strategy_name']}",
            f"Mode: {s.get('mode', 'unknown')}",
            f"State: {state}",
            f"Symbol: {s.get('symbol', 'unknown')}",
            f"Timeframe: {s.get('timeframe', 'unknown')}",
            f"Allocation: {alloc_text}",
            f"Open orders: {open_order_count}",
            f"Open positions: {len(positions)}",
        ])
        if positions:
            lines.append("Open positions:")
            lines.extend(
                f"  • {p['symbol']} qty={p['quantity']} unrealized=${p['unrealized_pnl']:.2f}"
                for p in positions
            )
    return "\n".join(lines)


def format_strategy_status_summary(strategies: list[dict]) -> str:
    running = sum(1 for s in strategies if s.get("running"))
    open_orders = sum(int(s.get("open_order_count") or len(s.get("open_orders") or [])) for s in strategies)
    open_positions = sum(len(s.get("open_positions") or []) for s in strategies)
    state_icon = "🟢" if running else "⏸"
    header = "\n".join([
        f"{state_icon} Bot Status · {_thai_datetime()}",
        f"Running loops: {running}/{len(strategies)}",
        f"Open orders: {open_orders}",
        f"Open positions: {open_positions}",
        "",
    ])
    return f"{header}{format_strategy_list(strategies)}"


def format_pnl_summary(total_pnl: dict, strategy_pnls: list[dict]) -> str:
    lines = [
        "📊 P&L",
        f"Daily:  ${total_pnl['daily']:,.2f}",
        f"Total:  ${total_pnl['total']:,.2f}",
    ]
    for pnl in strategy_pnls:
        lines.extend([
            "",
            f"{pnl.get('loop_id', 'unknown')} / {pnl.get('strategy_name', 'unknown')}",
            f"Daily:  ${pnl['daily']:,.2f}",
            f"Total:  ${pnl['total']:,.2f}",
        ])
    return "\n".join(lines)


def _pct(value) -> str:
    return "unset" if value is None else f"{float(value):.0%}"


def format_risk_status(status: dict) -> str:
    if not status.get("available", True):
        return "Risk Status\nUnavailable"
    strategy_stops = status.get("strategy_kill_switches") or {}
    lines = [
        "Risk Status",
        f"Global kill switch: {'ON' if status.get('global_kill_switch') else 'off'}",
        f"Circuit breaker: {'ON' if status.get('circuit_breaker') else 'off'}",
        f"Daily loss limit: {_pct(status.get('daily_loss_limit_pct'))}",
        f"Max drawdown: {_pct(status.get('max_drawdown_limit_pct'))}",
        f"Max exposure: {_pct(status.get('max_exposure_pct'))}",
    ]
    if status.get("global_kill_reason"):
        lines.append(f"Global reason: {status['global_kill_reason']}")
    if status.get("circuit_reason"):
        lines.append(f"Circuit reason: {status['circuit_reason']}")
    if strategy_stops:
        lines.append("Strategy stops:")
        lines.extend(f"  • {sid}: {reason}" for sid, reason in strategy_stops.items())
    else:
        lines.append("Strategy stops: none")
    return "\n".join(lines)


def format_ab_result(result: "ABTestResult") -> str:
    if result.outcome == "CHALLENGER_APPLIED":
        emoji = "✅"
        action = f"Challenger APPLIED (improvement: {(result.challenger_win_rate - result.champion_win_rate):+.1%})"
    else:
        emoji = "🔄"
        action = f"Champion retained (no significant improvement)"
    return (
        f"{emoji} A/B Test Complete  [run={result.run_id}]\n"
        f"Champion: {result.champion_win_rate:.1%}  →  Challenger: {result.challenger_win_rate:.1%}\n"
        f"p-value: {result.p_value:.4f}  |  {action}"
    )


class TelegramConnectivityMonitor:
    def __init__(self, *, probe, logger, interval_seconds: float = 60.0):
        self._probe = probe
        self._logger = logger
        self._interval_seconds = interval_seconds
        self._unhealthy = False

    async def check_once(self) -> None:
        try:
            await self._probe()
        except Exception as exc:
            if not self._unhealthy:
                self._logger.warning("Telegram connectivity check failed; retrying: %s", exc)
            self._unhealthy = True
            return

        if self._unhealthy:
            self._logger.info("Telegram connectivity recovered after retry")
        self._unhealthy = False

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self._interval_seconds)
            await self.check_once()


class TelegramNotifier:

    def __init__(self, token: str, chat_id: str, controller: EngineController):
        self._token = token
        self._chat_id = chat_id
        self._controller = controller
        self._app = None  # initialized in start()
        self._health_task = None
        self._health_monitor = None

    def _authorized(self, update) -> bool:
        chat = getattr(update, "effective_chat", None)
        chat_id = getattr(chat, "id", None)
        if chat_id is None or not isinstance(chat_id, (int, str)):
            return True
        return str(chat_id) == str(self._chat_id)

    async def _reject_if_unauthorized(self, update) -> bool:
        if self._authorized(update):
            return False
        await update.message.reply_text("Unauthorized chat.")
        return True

    async def send(self, text: str) -> None:
        if self._app is None:
            logger.warning("TelegramNotifier.send() called but bot not started — message dropped")
            return
        await self._app.bot.send_message(chat_id=self._chat_id, text=text)

    async def on_signal(self, signal: Signal) -> None:
        if signal.side != "HOLD":
            await self.send(format_signal_alert(signal))

    async def on_order_filled(self, order: Order, entry_price: float, realized_pnl: float) -> None:
        await self.send(format_order_alert(order, entry_price, realized_pnl))

    async def on_daily_limit_hit(self) -> None:
        await self.send("⚠️ Daily loss limit reached — bot paused")

    async def send_daily_summary(self, repo, day: str | None = None,
                                 balance: float | None = None) -> None:
        """Pull one day's decisions + closed trades from DB and send a summary to
        Telegram. `day` is an ISO date (YYYY-MM-DD); defaults to today.
        limit=500 covers a busy day (incl. fast
        1m-loop rehearsals) without truncation."""
        decisions = await repo.get_decisions(limit=500)
        from datetime import date
        day = day or date.today().isoformat()
        day_decisions = [d for d in decisions if d["timestamp"][:10] == day]

        total = len(day_decisions)
        placed = sum(1 for d in day_decisions if d["final_decision"] == "PLACED")
        rejected = sum(1 for d in day_decisions if d["final_decision"] == "REJECTED")
        hold = total - placed - rejected

        breakdown: dict[str, int] = {}
        for d in day_decisions:
            if d["final_decision"] == "REJECTED" and d["rejection_reason"]:
                breakdown[d["rejection_reason"]] = breakdown.get(d["rejection_reason"], 0) + 1

        # Performance block from closed trades. Same realized_pnl/exit_time fields
        # the /pnl command uses (live_controller.get_pnl). ponytail: realized PnL +
        # balance, not mark-to-market equity — equity needs a live price fetch the
        # notifier has no client for, and a daily digest doesn't need intraday marks.
        trades = await repo.get_trade_history()
        day_trades = [t for t in trades if (t.get("exit_time") or "")[:10] == day]
        day_pnl = sum((t.get("realized_pnl") or 0) for t in day_trades)
        total_pnl = sum((t.get("realized_pnl") or 0) for t in trades)
        wins = sum(1 for t in day_trades if (t.get("realized_pnl") or 0) > 0)
        n = len(day_trades)
        open_order_count = None
        if hasattr(repo, "get_orders"):
            orders = await repo.get_orders()
            open_order_count = sum(
                1 for order in orders
                if str(order.get("status", "")).upper() in {"PENDING", "OPEN"}
            )

        text = format_daily_summary(
            total, placed, rejected, hold, breakdown, day=day,
            day_pnl=day_pnl, total_pnl=total_pnl, wins=wins, trades=n,
            balance=balance, trade_rows=day_trades, open_order_count=open_order_count,
        )
        await self.send(text)

    async def send_weekly_summary(self, repo) -> None:
        trades = await repo.get_trade_history()
        await self.send(format_weekly_summary(trades))

    async def send_drift_alert(self, event) -> None:
        from notifier.telegram import format_drift_alert
        await self.send(format_drift_alert(event))

    async def send_retrain_complete(self, holdout_accuracy: float, model_id: str) -> None:
        from notifier.telegram import format_retrain_complete
        await self.send(format_retrain_complete(holdout_accuracy, model_id))

    async def send_ab_result(self, result) -> None:
        from notifier.telegram import format_ab_result
        await self.send(format_ab_result(result))

    async def send_strategy_switch(self, sw) -> None:
        from notifier.telegram import format_strategy_switch
        await self.send(format_strategy_switch(sw))

    # ── Command handlers ──────────────────────────────────────────────────

    async def cmd_help(self, update, context) -> None:
        await update.message.reply_text(
            "Commands:\n"
            "/status\n/pnl\n/strategies\n/strategy_status <loop_id>\n"
            "/start_bot\n/stop_bot\n/restart_bot\n"
            "/start_strategy <loop_id>\n/stop_strategy <loop_id>\n"
            "/portfolio\n/open_positions\n/closed_positions\n"
            "/signals\n/allocation\n/risk_status\n/health"
        )

    async def cmd_status(self, update, context) -> None:
        args = getattr(context, "args", []) if context else []
        if args:
            try:
                status = await self._controller.get_strategy_status(args[0])
            except KeyError as exc:
                await update.message.reply_text(str(exc))
                return
            await update.message.reply_text(format_strategy_list([status]))
            return
        strategies = await self._controller.get_strategies()
        if isinstance(strategies, list) and strategies:
            await update.message.reply_text(format_strategy_status_summary(strategies))
            return

        status = await self._controller.get_status()
        positions = status.get("open_positions", [])
        open_order_count = int(status.get("open_order_count") or len(status.get("open_orders") or []))
        pos_text = "\n".join(
            f"  • {p['symbol']}  qty={p['quantity']}  unrealised=${p['unrealized_pnl']:.2f}"
            for p in positions
        ) or "  None"
        text = (
            f"{'🟢 Running' if status['running'] else '⏸ Paused'} · {_thai_datetime()}\n"
            f"Strategy: {status['strategy_id']}\n"
            f"Open orders: {open_order_count}\n"
            f"Open positions: {len(positions)}\n"
            f"Open positions:\n{pos_text}"
        )
        await update.message.reply_text(text)

    async def cmd_strategies(self, update, context) -> None:
        strategies = await self._controller.get_strategies()
        await update.message.reply_text(format_strategy_list(strategies))

    async def cmd_strategy_status(self, update, context) -> None:
        if not context.args:
            await update.message.reply_text("Usage: /strategy_status <loop_id>")
            return
        try:
            status = await self._controller.get_strategy_status(context.args[0])
        except KeyError as exc:
            await update.message.reply_text(str(exc))
            return
        await update.message.reply_text(format_strategy_list([status]))

    async def cmd_start_bot(self, update, context) -> None:
        if await self._reject_if_unauthorized(update):
            return
        await self._controller.start_bot()
        await update.message.reply_text("Bot started.")

    async def cmd_stop_bot(self, update, context) -> None:
        if await self._reject_if_unauthorized(update):
            return
        await self._controller.stop_bot()
        await update.message.reply_text("Bot stopped. Open exchange-side protection is unchanged.")

    async def cmd_restart_bot(self, update, context) -> None:
        if await self._reject_if_unauthorized(update):
            return
        await self._controller.restart_bot()
        await update.message.reply_text("Bot restarted.")

    async def cmd_start_strategy(self, update, context) -> None:
        if await self._reject_if_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /start_strategy <loop_id>")
            return
        loop_id = context.args[0]
        try:
            await self._controller.start_strategy(loop_id)
        except KeyError as exc:
            await update.message.reply_text(str(exc))
            return
        await update.message.reply_text(f"{loop_id} started.")

    async def cmd_stop_strategy(self, update, context) -> None:
        if await self._reject_if_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /stop_strategy <loop_id>")
            return
        loop_id = context.args[0]
        try:
            await self._controller.stop_strategy(loop_id)
        except KeyError as exc:
            await update.message.reply_text(str(exc))
            return
        await update.message.reply_text(f"{loop_id} stopped.")

    async def cmd_pause(self, update, context) -> None:
        await self._controller.pause()
        await update.message.reply_text("⏸ Bot paused — no new orders will be placed.")

    async def cmd_resume(self, update, context) -> None:
        await self._controller.resume()
        await update.message.reply_text("▶️ Bot resumed.")

    async def cmd_pnl(self, update, context) -> None:
        args = getattr(context, "args", []) if context else []
        if args:
            try:
                pnl = await self._controller.get_strategy_pnl(args[0])
            except KeyError as exc:
                await update.message.reply_text(str(exc))
                return
            title = f"📊 P&L — {pnl.get('loop_id', args[0])} / {pnl.get('strategy_name', 'unknown')}"
        else:
            pnl = await self._controller.get_pnl()
            strategies = await self._controller.get_strategies()
            if isinstance(strategies, list) and strategies:
                strategy_pnls = []
                for strategy in strategies:
                    try:
                        strategy_pnls.append(await self._controller.get_strategy_pnl(strategy["loop_id"]))
                    except KeyError:
                        continue
                await update.message.reply_text(format_pnl_summary(pnl, strategy_pnls))
                return
            title = "📊 P&L"
        await update.message.reply_text(
            f"{title}\n"
            f"Daily:  ${pnl['daily']:,.2f}\n"
            f"Total:  ${pnl['total']:,.2f}"
        )

    async def cmd_portfolio(self, update, context) -> None:
        status = await self._controller.get_status()
        await update.message.reply_text(f"Open positions: {len(status.get('open_positions') or [])}")

    async def cmd_open_positions(self, update, context) -> None:
        status = await self._controller.get_status()
        positions = status.get("open_positions") or []
        if not positions:
            await update.message.reply_text("Open positions: none")
            return
        await update.message.reply_text("\n".join(
            f"{p['symbol']} qty={p['quantity']} unrealized={p['unrealized_pnl']:.2f}"
            for p in positions
        ))

    async def cmd_closed_positions(self, update, context) -> None:
        pnl = await self._controller.get_pnl()
        await update.message.reply_text(f"Closed position P&L total: {pnl['total']:,.2f}")

    async def cmd_signals(self, update, context) -> None:
        await update.message.reply_text("Recent signals are available in strategy reports after migration.")

    async def cmd_allocation(self, update, context) -> None:
        strategies = await self._controller.get_strategies()
        lines = ["Allocation"]
        for s in strategies:
            pct = s.get("allocation_pct")
            if isinstance(pct, float):
                lines.append(f"{s['loop_id']} / {s['strategy_name']}: {pct:.0%}")
            else:
                lines.append(f"{s['loop_id']} / {s['strategy_name']}: unset")
        await update.message.reply_text("\n".join(lines))

    async def cmd_risk_status(self, update, context) -> None:
        status = await self._controller.get_risk_status()
        await update.message.reply_text(format_risk_status(status))

    async def cmd_health(self, update, context) -> None:
        strategies = await self._controller.get_strategies()
        running = sum(1 for s in strategies if s.get("running"))
        await update.message.reply_text(f"Health: ok\nRunning loops: {running}/{len(strategies)}")

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
        self._app.add_handler(CommandHandler("start", self.cmd_help))
        self._app.add_handler(CommandHandler("help", self.cmd_help))
        self._app.add_handler(CommandHandler("status", self.cmd_status))
        self._app.add_handler(CommandHandler("strategies", self.cmd_strategies))
        self._app.add_handler(CommandHandler("strategy_status", self.cmd_strategy_status))
        self._app.add_handler(CommandHandler("start_bot", self.cmd_start_bot))
        self._app.add_handler(CommandHandler("stop_bot", self.cmd_stop_bot))
        self._app.add_handler(CommandHandler("restart_bot", self.cmd_restart_bot))
        self._app.add_handler(CommandHandler("start_strategy", self.cmd_start_strategy))
        self._app.add_handler(CommandHandler("stop_strategy", self.cmd_stop_strategy))
        self._app.add_handler(CommandHandler("pause", self.cmd_pause))
        self._app.add_handler(CommandHandler("resume", self.cmd_resume))
        self._app.add_handler(CommandHandler("pnl", self.cmd_pnl))
        self._app.add_handler(CommandHandler("portfolio", self.cmd_portfolio))
        self._app.add_handler(CommandHandler("open_positions", self.cmd_open_positions))
        self._app.add_handler(CommandHandler("closed_positions", self.cmd_closed_positions))
        self._app.add_handler(CommandHandler("signals", self.cmd_signals))
        self._app.add_handler(CommandHandler("allocation", self.cmd_allocation))
        self._app.add_handler(CommandHandler("risk_status", self.cmd_risk_status))
        self._app.add_handler(CommandHandler("health", self.cmd_health))
        self._app.add_handler(CommandHandler("close", self.cmd_close))
        await self._app.initialize()
        await self._app.updater.start_polling()
        await self._app.start()
        interval = float(os.getenv("TELEGRAM_HEALTH_CHECK_SECONDS", "60"))
        if interval > 0:
            self._health_monitor = TelegramConnectivityMonitor(
                probe=self._app.bot.get_me,
                logger=logger,
                interval_seconds=interval,
            )
            self._health_task = asyncio.create_task(self._health_monitor.run())

    async def stop(self) -> None:
        if self._health_task:
            self._health_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._health_task
            self._health_task = None
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
