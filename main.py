# main.py
"""
Main entry point. Reads config, wires all components, starts engine loop + API + Telegram.

Usage:
    python main.py                # live trading (reads BINANCE_TESTNET from .env)
    PAPER_TRADING=true python main.py  # paper trading mode
"""
import asyncio
import os
import aiosqlite
import uvicorn

from core.config import Settings
from core.engine import Engine
from core.live_controller import LiveEngineController
from data.fetcher import DataFetcher
from db.schema import init_db
from db.repository import Repository
from exchange.binance import BinanceExchange
from exchange.paper import PaperExchange
from notifier.logger import get_logger
from notifier.telegram import TelegramNotifier
from risk.manager import RiskManager
from strategy.ml.dummy_model import DummyModel
from strategy.rsi_macd import RsiMacdStrategy
from api.main import create_app


async def run():
    settings = Settings()
    # makedirs must run before get_logger() — the rotating file handler opens
    # logs/trading.log on construction, which fails if the dir does not exist.
    os.makedirs("logs", exist_ok=True)
    os.makedirs("db", exist_ok=True)
    logger = get_logger("main", "logs/trading.log")

    paper_mode = os.getenv("PAPER_TRADING", "false").lower() == "true"

    if paper_mode:
        exchange = PaperExchange(initial_balance={"USDT": 10000.0})
        logger.info("Starting in PAPER TRADING mode")
    else:
        exchange = BinanceExchange(
            api_key=settings.binance_api_key,
            api_secret=settings.binance_api_secret,
            testnet=settings.binance_testnet,
        )
        mode = "TESTNET" if settings.binance_testnet else "MAINNET"
        logger.info(f"Starting in LIVE mode ({mode})")

    strategy = RsiMacdStrategy(ml_model=DummyModel(confidence=0.8))

    # ONE shared RiskManager for all engines — enforces portfolio-level limits
    risk_manager = RiskManager(
        max_position_pct=float(os.getenv("MAX_POSITION_PCT", "0.05")),
        max_open_positions=int(os.getenv("MAX_OPEN_POSITIONS", "5")),
        daily_loss_limit_pct=float(os.getenv("DAILY_LOSS_LIMIT_PCT", "0.03")),
        confidence_threshold=float(os.getenv("CONFIDENCE_THRESHOLD", "0.6")),
    )

    engine = Engine(
        exchange=exchange,
        strategy=strategy,
        symbol="BTC/USDT",
        timeframe="1h",
        risk_manager=risk_manager,
    )
    engine.is_running = True

    async with aiosqlite.connect("db/trades.db") as conn:
        await init_db(conn)
        repo = Repository(conn)

        balance = await exchange.get_balance()
        daily_start = balance.get("USDT", 10000.0)
        # Seed the daily-loss circuit breaker so RiskManager has a baseline to
        # measure drawdown against from the very first iteration.
        risk_manager.record_daily_start_balance(daily_start)
        controller = LiveEngineController(engine=engine, repo=repo, daily_start_balance=daily_start)

        notifier = None
        if settings.telegram_bot_token and settings.telegram_chat_id:
            notifier = TelegramNotifier(
                token=settings.telegram_bot_token,
                chat_id=settings.telegram_chat_id,
                controller=controller,
            )
            await notifier.start()
            logger.info("Telegram bot started")

        app = create_app(repo)

        async def trading_loop():
            from datetime import date
            fetcher = DataFetcher(
                exchange_id="binance",
                testnet=settings.binance_testnet if not paper_mode else True,
            )
            last_reset_date = None
            consecutive_failures = 0

            while True:
                # UTC midnight daily reset — resets daily loss limit
                today = date.today()
                if today != last_reset_date:
                    bal = await exchange.get_balance()
                    risk_manager.reset_daily(bal.get("USDT", 0.0))
                    last_reset_date = today

                if not engine.is_running:
                    await asyncio.sleep(10)
                    continue

                try:
                    candles = await fetcher.fetch_ohlcv("BTC/USDT", "1h", limit=100)
                    # Mark-to-market equity = free USDT + value of open positions at the
                    # latest close. We use equity (not free USDT alone) because an open
                    # position's unrealized loss must count toward the daily drawdown —
                    # otherwise the 3% circuit breaker would never see intraday losses
                    # that are still sitting in open positions.
                    bal = await exchange.get_balance()
                    positions = await exchange.get_positions()
                    last_close = float(candles[-1][4]) if candles else 0.0
                    equity = bal.get("USDT", 0.0) + sum(p.quantity * last_close for p in positions)
                    risk_manager.record_current_balance(equity)

                    await engine.process_candles(candles)
                    consecutive_failures = 0
                except Exception as e:
                    consecutive_failures += 1
                    logger.error(f"Engine loop error (attempt {consecutive_failures}): {e}")
                    if consecutive_failures >= 5 and notifier:
                        await notifier.send("⚠️ Data feed lost — 5 consecutive failures, trading paused")
                        engine.is_running = False

                await asyncio.sleep(3600)  # run once per closed hourly candle

        config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="warning")
        server = uvicorn.Server(config)

        await asyncio.gather(
            trading_loop(),
            server.serve(),
        )

        if notifier:
            await notifier.stop()


if __name__ == "__main__":
    asyncio.run(run())
