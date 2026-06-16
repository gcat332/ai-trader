# main.py
"""
Main entry point / composition root. Reads config, wires all components, then
starts the trading loop + API + Telegram concurrently.

Strategy construction lives in core/strategy_factory.py and the operational loop
in core/trading_loop.py — this file only does the wiring.

Usage:
    python main.py                # live trading (reads BINANCE_TESTNET from .env)
    PAPER_TRADING=true python main.py  # paper trading mode
"""
import asyncio
import os

import aiosqlite
import uvicorn

from api.main import create_app
from core.config import Settings
from core.drift_monitor import DriftDetector
from core.engine import Engine
from core.live_controller import LiveEngineController
from core.strategy_factory import build_strategy
from core.trading_loop import run_trading_loop
from db.repository import Repository
from db.schema import init_db
from exchange.binance import BinanceExchange
from exchange.paper import PaperExchange
from ml.retrainer import ModelRetrainer
from notifier.logger import get_logger
from notifier.telegram import TelegramNotifier
from risk.manager import RiskManager


async def run():
    settings = Settings()
    # makedirs must run before get_logger() — the rotating file handler opens
    # logs/trading.log on construction, which fails if the dir does not exist.
    os.makedirs("logs", exist_ok=True)
    os.makedirs("db", exist_ok=True)
    logger = get_logger("main", "logs/trading.log")

    paper_mode = os.getenv("PAPER_TRADING", "false").lower() == "true"

    # Fail fast on missing secrets instead of crashing on the first signed API call.
    settings.validate(
        paper_mode=paper_mode,
        strategy_mode=os.getenv("STRATEGY_MODE", "rule_based"),
        arbiter_mode=os.getenv("ARBITER_MODE", "rule"),
    )

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

    strategy = build_strategy()

    # Symbol/timeframe and loop cadence are env-driven so a go-live rehearsal can
    # run a fast 1m loop without touching prod defaults (1h candle, hourly poll).
    symbol = os.getenv("TRADING_SYMBOL", "BTC/USDT")
    timeframe = os.getenv("TRADING_TIMEFRAME", "1h")

    drift_detector = DriftDetector(
        win_rate_threshold=float(os.getenv("DRIFT_WIN_RATE_THRESHOLD", "0.40")),
        calibration_threshold=float(os.getenv("DRIFT_CALIBRATION_THRESHOLD", "0.20")),
        min_samples=int(os.getenv("DRIFT_MIN_SAMPLES", "30")),
    )
    retrainer = ModelRetrainer(
        min_samples=int(os.getenv("RETRAIN_MIN_SAMPLES", "50")),
        models_dir=os.getenv("MODELS_DIR", "models"),
    )

    # ONE shared RiskManager for all engines — enforces portfolio-level limits
    risk_manager = RiskManager(
        max_position_pct=float(os.getenv("MAX_POSITION_PCT", "0.05")),
        max_open_positions=int(os.getenv("MAX_OPEN_POSITIONS", "5")),
        daily_loss_limit_pct=float(os.getenv("DAILY_LOSS_LIMIT_PCT", "0.03")),
        confidence_threshold=float(os.getenv("CONFIDENCE_THRESHOLD", "0.6")),
    )

    async with aiosqlite.connect("db/trades.db") as conn:
        await init_db(conn)
        repo = Repository(conn)

        engine = Engine(
            exchange=exchange,
            strategy=strategy,
            symbol=symbol,
            timeframe=timeframe,
            risk_manager=risk_manager,
            repo=repo,
            state_path=os.getenv("ENGINE_STATE_PATH", "db/engine_state.json"),
        )
        engine.is_running = True

        # Startup reconciliation: surface any open position the exchange holds that we
        # have no tracked decision for (e.g. opened before a crash). It will still be
        # protected by its exchange-side OCO, but the outcome won't be attributable.
        try:
            # Restart recovery: re-register the bot's own trading symbol as an open
            # position from its balance (entry price unknown until the next fill).
            # Pre-existing holdings in other assets are ignored — see
            # BinanceExchange.get_positions for why.
            await exchange.seed_open_positions([symbol])
            open_positions = await exchange.get_positions()
            tracked = set(engine._active_decisions)
            for p in open_positions:
                if p.symbol not in tracked:
                    logger.warning(
                        f"Reconcile: untracked open position {p.symbol} qty={p.quantity} "
                        "(no decision record — outcome will not be attributed)"
                    )
        except Exception as e:
            logger.error(f"Startup reconciliation failed: {e}")

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

        app = create_app(repo, exchange=exchange, controller=controller)

        # Bind localhost by default so the trading-control API is not reachable from
        # the network. Set API_HOST=0.0.0.0 for remote access — and set API_KEY too,
        # or the control endpoints are exposed unauthenticated.
        api_host = os.getenv("API_HOST", "127.0.0.1")
        api_port = int(os.getenv("API_PORT", "8000"))
        if api_host not in ("127.0.0.1", "localhost") and not os.getenv("API_KEY"):
            logger.warning(
                f"API bound to {api_host} with no API_KEY set — trading controls are "
                "exposed unauthenticated. Set API_KEY or bind to localhost."
            )
        config = uvicorn.Config(app, host=api_host, port=api_port, log_level="warning")
        server = uvicorn.Server(config)

        # return_exceptions=True so a fatal error in one task does not cancel the other
        # (e.g. the trading loop dying must not take the dashboard API down with it).
        await asyncio.gather(
            run_trading_loop(
                exchange=exchange,
                paper_mode=paper_mode,
                strategy=strategy,
                symbol=symbol,
                timeframe=timeframe,
                risk_manager=risk_manager,
                engine=engine,
                repo=repo,
                drift_detector=drift_detector,
                retrainer=retrainer,
                notifier=notifier,
                logger=logger,
            ),
            server.serve(),
            return_exceptions=True,
        )

        if notifier:
            await notifier.stop()


if __name__ == "__main__":
    asyncio.run(run())
