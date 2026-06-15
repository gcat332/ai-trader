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
from core.drift_monitor import DriftDetector
from core.engine import Engine
from core.live_controller import LiveEngineController
from data.fetcher import DataFetcher
from db.schema import init_db
from db.repository import Repository
from exchange.binance import BinanceExchange
from exchange.paper import PaperExchange
from ml.ab_tester import ModelABTester
from ml.retrainer import ModelRetrainer
from notifier.logger import get_logger
from notifier.telegram import TelegramNotifier
from risk.manager import RiskManager
from strategy.ml.dummy_model import DummyModel
from strategy.rsi_macd import RsiMacdStrategy
from api.main import create_app
from strategy.base import BaseStrategy


def _cooldown_elapsed(last_retrain_iso: str, days: int) -> bool:
    from datetime import datetime, timedelta, timezone
    last = datetime.fromisoformat(last_retrain_iso)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last) >= timedelta(days=days)


def _build_strategy() -> BaseStrategy:
    mode = os.getenv("STRATEGY_MODE", "rule_based")
    ml_model = DummyModel(confidence=float(os.getenv("ML_CONFIDENCE", "0.75")))
    gatekeeper = RsiMacdStrategy(ml_model=ml_model)

    match mode:
        case "rule_based":
            return gatekeeper

        case "hybrid":
            from strategy.ml.claude_strategy import ClaudeStrategy
            from strategy.hybrid_strategy import HybridStrategy
            validator = ClaudeStrategy(
                model=os.getenv("CLAUDE_STRATEGY_MODEL"),
                confidence_threshold=float(os.getenv("CONFIDENCE_THRESHOLD", "0.60")),
            )
            return HybridStrategy(gatekeeper=gatekeeper, validator=validator)

        case "claude_ai":
            from strategy.ml.claude_strategy import ClaudeStrategy
            return ClaudeStrategy(
                model=os.getenv("CLAUDE_STRATEGY_MODEL"),
                confidence_threshold=float(os.getenv("CONFIDENCE_THRESHOLD", "0.60")),
            )

        case "multi":
            from strategy.bollinger_reversion import BollingerReversionStrategy
            from strategy.ema_cross import EmaCrossStrategy
            from strategy.meta_strategy import MetaStrategy
            techniques = {
                "rsi_macd": gatekeeper,
                "bollinger_reversion": BollingerReversionStrategy(ml_model=DummyModel(confidence=0.75)),
                "ema_cross": EmaCrossStrategy(ml_model=DummyModel(confidence=0.75)),
            }
            return MetaStrategy(techniques, active=os.getenv("DEFAULT_STRATEGY", "rsi_macd"))

        case _:
            raise ValueError(
                f"Unknown STRATEGY_MODE={mode!r}. "
                "Valid: rule_based, hybrid, claude_ai, multi"
            )


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

    strategy = _build_strategy()

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
            symbol="BTC/USDT",
            timeframe="1h",
            risk_manager=risk_manager,
            repo=repo,
        )
        engine.is_running = True

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

        app = create_app(repo, exchange=exchange)

        async def trading_loop():
            from datetime import date
            from strategy.meta_strategy import MetaStrategy
            from strategy.regime import RegimeClassifier
            from core.strategy_arbiter import StrategyArbiter
            from core.live_outcome_tracker import LiveOutcomeTracker
            fetcher = DataFetcher(
                exchange_id="binance",
                testnet=settings.binance_testnet if not paper_mode else True,
            )
            last_reset_date = None
            consecutive_failures = 0

            # Multi-mode components (only used when strategy is a MetaStrategy)
            outcome_tracker = LiveOutcomeTracker()
            arbiter = None
            if isinstance(strategy, MetaStrategy):
                rule_arbiter = StrategyArbiter(
                    strategies=strategy.strategy_ids,
                    swap_margin=float(os.getenv("SWAP_MARGIN", "0.10")),
                    min_regime_samples=int(os.getenv("MIN_REGIME_SAMPLES", "20")),
                    epsilon=float(os.getenv("STRATEGY_EPSILON", "0.10")),
                )
                if os.getenv("ARBITER_MODE", "rule") == "claude":
                    from core.claude_arbiter import ClaudeStrategyArbiter
                    arbiter = ClaudeStrategyArbiter(
                        strategies=strategy.strategy_ids,
                        fallback=rule_arbiter, repo=repo,
                        model=os.getenv("CLAUDE_ARBITER_MODEL"),
                    )
                else:
                    arbiter = rule_arbiter

            while True:
                # Whole loop body is wrapped so any transient failure (balance fetch,
                # daily reset, OHLCV fetch, processing) is caught and counted — the loop
                # is self-healing and never propagates an exception that would tear down
                # the gathered uvicorn server.
                try:
                    # UTC midnight daily reset — resets daily loss limit
                    today = date.today()
                    if today != last_reset_date:
                        bal = await exchange.get_balance()
                        risk_manager.reset_daily(bal.get("USDT", 0.0))
                        last_reset_date = today

                    if engine.is_running:
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

                        # Record live trade closes so drift profiles have real data.
                        if isinstance(strategy, MetaStrategy):
                            positions_now = await exchange.get_positions()
                            for trade in outcome_tracker.detect_closed(positions_now, last_close):
                                await engine.record_trade_outcome(trade)
                            outcome_tracker.snapshot(await exchange.get_positions())

                        # Drift check every N candles (configurable via DRIFT_CHECK_INTERVAL env var)
                        _drift_tick = getattr(trading_loop, "_drift_tick", 0) + 1
                        trading_loop._drift_tick = _drift_tick

                        drift_interval = int(os.getenv("DRIFT_CHECK_INTERVAL", "10"))

                        if isinstance(strategy, MetaStrategy):
                            # Regime-aware arbitration replaces the Phase-9 retrain block
                            # when running in multi mode.
                            if _drift_tick % drift_interval == 0:
                                event = await drift_detector.check(repo)
                                if event is not None:
                                    if notifier:
                                        await notifier.send_drift_alert(event)
                                    import pandas as pd
                                    df_candles = pd.DataFrame(
                                        candles,
                                        columns=["timestamp", "open", "high", "low", "close", "volume"],
                                    )
                                    current_regime = RegimeClassifier().classify(df_candles)
                                    profiles = await repo.get_strategy_profiles()
                                    last_switch = await repo.get_last_switch_time()
                                    if last_switch is None or _cooldown_elapsed(
                                        last_switch,
                                        days=int(os.getenv("SWAP_COOLDOWN_DAYS", "1")),
                                    ):
                                        from core.claude_arbiter import ClaudeStrategyArbiter
                                        decision = (
                                            await arbiter.decide(current_regime, strategy.active, profiles)
                                            if isinstance(arbiter, ClaudeStrategyArbiter)
                                            else arbiter.decide(current_regime, strategy.active, profiles)
                                        )
                                        await repo.insert_strategy_switch(decision)
                                        if notifier:
                                            await notifier.send_strategy_switch(decision)
                                        if decision.decision in ("SWAP", "EXPLORE"):
                                            strategy.set_active(decision.to_strategy)
                                        elif decision.decision == "RETRAIN" and hasattr(strategy, "ml_model"):
                                            model = await retrainer.retrain(repo)
                                            if model is not None:
                                                strategy.ml_model = model

                        # ML retrain + A/B test only applies when strategy has an ml_model
                        # (i.e. rule_based / RsiMacdStrategy). HybridStrategy and
                        # ClaudeStrategy do not expose ml_model — skip this block entirely.
                        # When running in multi mode, the arbiter block above handles decisions.
                        elif hasattr(strategy, "ml_model"):
                            # If an A/B test is in progress, periodically evaluate it.
                            # evaluate() is a no-op (returns None) until min_trades of
                            # real champion outcomes have accumulated, so this is safe
                            # to call every drift tick. When a winner is found we apply
                            # it to the live strategy and conclude the A/B test.
                            if engine._ab_tester is not None and _drift_tick % drift_interval == 0:
                                result = await engine._ab_tester.evaluate(repo)
                                if result is not None:
                                    if notifier:
                                        await notifier.send_ab_result(result)
                                    if result.outcome == "CHALLENGER_APPLIED":
                                        strategy.ml_model = result.applied_model
                                        logger.info(
                                            f"A/B challenger applied as new champion "
                                            f"(win rate {result.challenger_win_rate:.1%} vs "
                                            f"{result.champion_win_rate:.1%}, p={result.p_value:.4f})"
                                        )
                                    else:
                                        logger.info(
                                            f"A/B champion retained (p={result.p_value:.4f})"
                                        )
                                    # A/B concluded either way; stop shadowing until the
                                    # next drift→retrain cycle spins up a fresh challenger.
                                    engine._ab_tester = None

                            if _drift_tick % drift_interval == 0:
                                event = await drift_detector.check(repo)
                                if event is not None:
                                    if notifier:
                                        await notifier.send_drift_alert(event)

                                    # Check 7-day retrain cooldown
                                    last_retrain = await repo.get_last_retrain_time()
                                    if last_retrain is None or _cooldown_elapsed(last_retrain, days=7):
                                        model = await retrainer.retrain(repo)
                                        if model is not None:
                                            if notifier:
                                                await notifier.send_retrain_complete(
                                                    model.holdout_accuracy, getattr(model, "model_id", "unknown")
                                                )
                                            ab_tester = ModelABTester(
                                                champion=strategy.ml_model,
                                                challenger=model,
                                                min_trades=int(os.getenv("AB_MIN_TRADES", "50")),
                                            )
                                            engine._ab_tester = ab_tester
                except Exception as e:
                    consecutive_failures += 1
                    logger.error(f"Engine loop error (attempt {consecutive_failures}): {e}")
                    if consecutive_failures >= 5 and notifier:
                        await notifier.send("⚠️ Data feed lost — 5 consecutive failures, trading paused")
                        engine.is_running = False

                # Poll faster while paused so /resume takes effect quickly; otherwise
                # run once per closed hourly candle.
                await asyncio.sleep(10 if not engine.is_running else 3600)

        config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="warning")
        server = uvicorn.Server(config)

        # return_exceptions=True so a fatal error in one task does not cancel the other
        # (e.g. the trading loop dying must not take the dashboard API down with it).
        await asyncio.gather(
            trading_loop(),
            server.serve(),
            return_exceptions=True,
        )

        if notifier:
            await notifier.stop()


if __name__ == "__main__":
    asyncio.run(run())
