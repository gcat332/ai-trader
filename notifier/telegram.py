# notifier/telegram.py
from core.models import Order, Signal
from notifier.engine_controller import EngineController


def format_signal_alert(signal: Signal) -> str:
    emoji = "🟢" if signal.side == "BUY" else "🔴"
    tp = f"{signal.take_profit:,.0f}" if signal.take_profit else "—"
    sl = f"{signal.stop_loss:,.0f}" if signal.stop_loss else "—"
    text = (
        f"{emoji} {signal.side}  {signal.symbol} @ {signal.entry_price:,.0f}\n"
        f"TP: {tp}  |  SL: {sl}\n"
        f"Confidence: {signal.confidence:.0%}  |  Strategy: {signal.strategy_id}"
    )
    if signal.narrative:
        # Add abbreviated narrative (first 2 parts only to keep message short)
        short = " | ".join(signal.narrative.split(" | ")[:2])
        text += f"\n{short}"
    return text


def format_daily_summary(
    total_evaluated: int,
    placed: int,
    rejected: int,
    hold: int,
    rejection_breakdown: dict[str, int],
) -> str:
    breakdown = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in rejection_breakdown.items())
    lines = [
        f"📊 Daily Decision Summary",
        f"Total evaluated: {total_evaluated}",
        f"✅ Placed: {placed}  |  ⛔ Rejected: {rejected}  |  ⏸ Hold: {hold}",
    ]
    if breakdown:
        lines.append(f"Rejections: {breakdown}")
    return "\n".join(lines)


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

    async def send_daily_summary(self, repo) -> None:
        """Pull today's decisions from DB and send summary to Telegram."""
        decisions = await repo.get_decisions(limit=200)
        from datetime import date
        today = date.today().isoformat()
        today_decisions = [d for d in decisions if d["timestamp"][:10] == today]

        total = len(today_decisions)
        placed = sum(1 for d in today_decisions if d["final_decision"] == "PLACED")
        rejected = sum(1 for d in today_decisions if d["final_decision"] == "REJECTED")
        hold = total - placed - rejected

        breakdown: dict[str, int] = {}
        for d in today_decisions:
            if d["final_decision"] == "REJECTED" and d["rejection_reason"]:
                breakdown[d["rejection_reason"]] = breakdown.get(d["rejection_reason"], 0) + 1

        text = format_daily_summary(total, placed, rejected, hold, breakdown)
        await self.send(text)

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
        await self._app.updater.start_polling()
        await self._app.start()

    async def stop(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
