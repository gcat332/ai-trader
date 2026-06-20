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
import inspect
import os

import aiosqlite
import uvicorn

from api.main import create_app
from core.allocation import AllocationManager
from core.config import Settings
from core.drift_monitor import DriftDetector
from core.engine import Engine
from core.live_controller import LiveEngineController
from core.loop_config import parse_loops, parse_runtime_configs
from core.loop_config import validate_loop_leverage_consistency
from core.macro_blackout import load_blackout
from core.supervisor import run_supervised
from core.strategy_factory import build_runtime_strategy, build_strategy
from core.strategy_manager import StrategyManager
from core.trading_loop import run_trading_loop
from types import SimpleNamespace
from db.repository import Repository
from db.schema import init_db
from exchange.binance import BinanceExchange
from exchange.binance_futures import BinanceFuturesExchange
from exchange.paper import PaperExchange
from exchange.paper_futures import PaperFuturesExchange
from ml.retrainer import ModelRetrainer
from notifier.logger import get_logger
from notifier.telegram import TelegramNotifier
from risk.manager import RiskManager
from scheduler.reports import run_report_scheduler


def _optional_float_env(name: str) -> float | None:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return None
    return float(raw)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_correlation_groups(raw: str | None) -> list[set[str]] | None:
    if raw is None or raw == "":
        return None
    groups = []
    for group_raw in raw.split(";"):
        group = {symbol.strip() for symbol in group_raw.split(",") if symbol.strip()}
        if group:
            groups.append(group)
    return groups or None


def _build_paper_exchange_for(cfg, initial_balance):
    """Build per-loop exchange for paper mode: PaperFuturesExchange if futures, else PaperExchange."""
    if getattr(cfg, "market", "spot") == "futures":
        return PaperFuturesExchange(
            initial_balance,
            leverage=getattr(cfg, "leverage", 1),
        )
    return PaperExchange(initial_balance=initial_balance)


def _build_live_exchange_for(cfg, settings, spot_exchange):
    if getattr(cfg, "market", "spot") == "futures":
        return BinanceFuturesExchange(
            api_key=settings.binance_api_key,
            api_secret=settings.binance_api_secret,
            testnet=settings.binance_testnet,
            leverage=getattr(cfg, "leverage", 1),
        )
    return spot_exchange


def _futures_engine_kwargs(cfg) -> dict:
    return {
        "market": cfg.market,
        "leverage": cfg.leverage,
        "risk_per_trade": cfg.risk_per_trade,
        "max_hold_hours": cfg.max_hold_hours,
        "reentry_cooldown_bars": cfg.reentry_cooldown_bars,
        "funding_skip_threshold": cfg.funding_skip_threshold,
        "liq_buffer_pct": float(os.getenv("LIQ_BUFFER_PCT", "0.0")),
        "slippage_pad": float(os.getenv("LIQ_SLIPPAGE_PAD", "0.0")),
    }


def _runtime_is_scheduled(runtime_config) -> bool:
    return runtime_config.mode != "BACKTEST"


def _warn_on_mixed_runtime_modes(runtime_configs, logger) -> None:
    modes = {cfg.mode for cfg in runtime_configs if _runtime_is_scheduled(cfg)}
    if len(modes) > 1:
        logger.warning(
            "Mixed LOOPn_MODE values are configured but per-loop exchange isolation is not enabled yet; "
            "mixed LIVE/PAPER execution is blocked by go-live validation."
        )


def _validate_go_live_safety(
    *,
    runtime_configs,
    settings: Settings,
    live_trading_enabled: bool,
    api_host: str,
    api_key: str | None,
) -> None:
    scheduled_modes = {cfg.mode for cfg in runtime_configs if _runtime_is_scheduled(cfg)}
    if "LIVE" in scheduled_modes and "PAPER" in scheduled_modes:
        raise ValueError(
            "Mixed LIVE/PAPER runtime modes require per-loop exchange isolation before go-live"
        )

    live_configs = [
        cfg for cfg in runtime_configs
        if cfg.mode == "LIVE" and _runtime_is_scheduled(cfg)
    ]
    if not live_configs:
        return

    if not live_trading_enabled:
        raise ValueError(
            "LIVE runtime configured; set LIVE_TRADING_ENABLED=true to arm real order placement"
        )

    network = "testnet" if settings.binance_testnet else "mainnet"
    if not settings.binance_api_key or not settings.binance_api_secret:
        raise ValueError(f"Live trading on {network} requires Binance {network} API key + secret")

    if api_host not in ("127.0.0.1", "localhost") and not api_key:
        raise ValueError("API_KEY is required when API_HOST is not localhost for LIVE trading")


async def _verify_futures_accounts(loop_specs, paper_mode: bool) -> None:
    """Pre-arm: every LIVE futures loop's exchange must be in one-way mode. Raises to abort startup."""
    if paper_mode:
        return
    from exchange.binance_futures import BinanceFuturesExchange
    for spec in loop_specs:
        if getattr(spec.config, "market", "spot") == "futures" and isinstance(spec.exchange, BinanceFuturesExchange):
            await spec.exchange.verify_account_mode()


async def _run_notifier_forever(notifier: TelegramNotifier, check_interval: float = 60.0) -> None:
    await notifier.start()
    try:
        while True:
            await asyncio.sleep(check_interval)
    finally:
        await notifier.stop()


async def _close_if_supported(resource, logger, name: str) -> None:
    close = getattr(resource, "close", None)
    if close is None:
        return
    try:
        result = close()
        if inspect.isawaitable(result):
            await result
        logger.info(f"Closed {name}")
    except Exception as exc:
        logger.warning(f"Failed to close {name}: {exc}")


async def run():
    settings = Settings()
    # makedirs must run before get_logger() — the rotating file handler opens
    # logs/trading.log on construction, which fails if the dir does not exist.
    os.makedirs("logs", exist_ok=True)
    os.makedirs("db", exist_ok=True)
    logger = get_logger("main", "logs/trading.log")

    # Bind localhost by default so the trading-control API is not reachable from
    # the network. Set API_HOST=0.0.0.0 for remote access — in LIVE this requires
    # API_KEY so control endpoints cannot be exposed unauthenticated.
    api_host = os.getenv("API_HOST", "127.0.0.1")
    api_port = int(os.getenv("API_PORT", "8000"))

    loops = parse_loops(os.environ)
    runtime_configs = parse_runtime_configs(os.environ)
    validate_loop_leverage_consistency(runtime_configs)
    _warn_on_mixed_runtime_modes(runtime_configs, logger)
    live_runtime_configured = any(
        cfg.mode == "LIVE" and _runtime_is_scheduled(cfg)
        for cfg in runtime_configs
    )
    # After LOOPn_MODE parsing, scheduled runtimes are either all LIVE or all
    # PAPER because mixed LIVE/PAPER is blocked until per-loop exchange isolation
    # exists. Use the parsed runtime mode as the execution source of truth.
    paper_mode = not live_runtime_configured
    _validate_go_live_safety(
        runtime_configs=runtime_configs,
        settings=settings,
        live_trading_enabled=_env_bool("LIVE_TRADING_ENABLED", False),
        api_host=api_host,
        api_key=os.getenv("API_KEY"),
    )

    # Fail fast on missing secrets instead of crashing on the first signed API call.
    settings.validate(
        paper_mode=not live_runtime_configured,
        strategy_mode=os.getenv("STRATEGY_MODE", "rule_based"),
        arbiter_mode=os.getenv("ARBITER_MODE", "rule"),
        runtime_configs=runtime_configs,
    )

    exchange = None
    try:
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

        # Loop specs: LOOPn_* env blocks → N concurrent loops on one shared account
        # (plan B/C). No LOOPn_* → one legacy loop using STRATEGY_MODE. Each loop gets
        # its own strategy, timeframe, engine-state file, and strategy_filter so the
        # shared exchange's positions are attributed to the right loop.
        loop_by_label = {lp.label: lp for lp in loops}
        loop_specs = []
        for cfg in runtime_configs:
            if not _runtime_is_scheduled(cfg):
                logger.info(f"Skipping {cfg.loop_id} in BACKTEST mode; run backtests through the backtest entrypoint")
                continue
            if cfg.loop_id == "legacy":
                loop_specs.append(SimpleNamespace(
                    config=cfg,
                    strategy=build_strategy(),
                    symbol=cfg.symbol,
                    timeframe=cfg.timeframe,
                    strategy_filter=None,
                    state_path=cfg.state_path,
                ))
                continue
            lp = loop_by_label[cfg.label]
            strategy = build_runtime_strategy(cfg, lp.get)
            loop_specs.append(SimpleNamespace(
                config=cfg,
                strategy=strategy,
                symbol=cfg.symbol,
                timeframe=cfg.timeframe,
                strategy_filter=None if cfg.strategy_mode == "multi" else cfg.strategy_instance_id,
                state_path=cfg.state_path,
            ))
        if loops:
            logger.info(
                f"Multi-loop mode: "
                f"{[(s.config.loop_id, s.config.strategy_name, s.timeframe) for s in loop_specs]}"
            )
        if not loop_specs:
            raise ValueError("No scheduled LIVE/PAPER runtime configs found")

        # ponytail: paper loops are isolated; live futures get futures clients while spot shares spot.
        for spec in loop_specs:
            spec.exchange = (
                _build_paper_exchange_for(spec.config, {"USDT": 10000.0})
                if paper_mode
                else _build_live_exchange_for(spec.config, settings, exchange)
            )
            if _env_bool('DRY_RUN', False) and not paper_mode:
                from exchange.dry_run import DryRunExchange
                spec.exchange = DryRunExchange(spec.exchange)
        await _verify_futures_accounts(loop_specs, paper_mode)

        allocation_manager = AllocationManager({
            spec.config.loop_id: spec.config.allocation_pct
            for spec in loop_specs
        })

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
            max_drawdown_limit_pct=_optional_float_env("MAX_DRAWDOWN_LIMIT_PCT"),
            max_exposure_pct=_optional_float_env("MAX_EXPOSURE_PCT"),
            correlation_groups=_parse_correlation_groups(os.getenv("CORRELATION_GROUPS")),
            blackout_windows=load_blackout(os.getenv("MACRO_BLACKOUT_FILE", "config/macro_blackout.json")),
        )

        async with aiosqlite.connect("db/trades.db") as conn:
            await init_db(conn)
            repo = Repository(conn)

            for spec in loop_specs:
                engine_kwargs = {}
                if spec.config.market == "futures":
                    engine_kwargs = _futures_engine_kwargs(spec.config)
                spec.engine = Engine(
                    exchange=spec.exchange,
                    strategy=spec.strategy,
                    symbol=spec.symbol,
                    timeframe=spec.timeframe,
                    risk_manager=risk_manager,
                    repo=repo,
                    state_path=spec.state_path,
                    allocation_manager=allocation_manager,
                    loop_id=spec.config.loop_id,
                    exit_on_opposite_signal=spec.config.exit_on_opposite_signal,
                    **engine_kwargs,
                )
                spec.engine.is_running = True

            # Startup reconciliation: surface any open position the exchange holds that we
            # have no tracked decision for (e.g. opened before a crash). It will still be
            # protected by its exchange-side OCO, but the outcome won't be attributable.
            try:
                # Restart recovery: re-register each loop's trading symbol as an open
                # position from its balance (entry price unknown until the next fill).
                if paper_mode:
                    for spec in loop_specs:
                        await spec.exchange.seed_open_positions([spec.symbol])
                        open_positions = await spec.exchange.get_positions()
                        tracked = set(spec.engine._active_decisions)
                        for p in open_positions:
                            if p.symbol not in tracked:
                                logger.warning(
                                    f"Reconcile: untracked open position {p.symbol} qty={p.quantity} "
                                    "(no decision record — outcome will not be attributed)"
                                )
                else:
                    symbols = {spec.symbol for spec in loop_specs}
                    await exchange.seed_open_positions(list(symbols))
                    open_positions = await exchange.get_positions()
                    tracked = {sym for spec in loop_specs for sym in spec.engine._active_decisions}
                    for p in open_positions:
                        if p.symbol not in tracked:
                            logger.warning(
                                f"Reconcile: untracked open position {p.symbol} qty={p.quantity} "
                                "(no decision record — outcome will not be attributed)"
                            )
            except Exception as e:
                logger.error(f"Startup reconciliation failed: {e}")

            api_exchange = loop_specs[0].exchange if paper_mode else exchange
            balance = await api_exchange.get_balance()
            daily_start = balance.get("USDT", 10000.0)
            # Seed the daily-loss circuit breaker so RiskManager has a baseline to
            # measure drawdown against from the very first iteration.
            risk_manager.record_daily_start_balance(daily_start)
            manager = StrategyManager(loop_specs)
            # Controller reports status for the first loop and pauses/resumes ALL loops.
            controller = LiveEngineController(
                engine=loop_specs[0].engine, repo=repo, daily_start_balance=daily_start,
                extra_engines=[s.engine for s in loop_specs[1:]], manager=manager,
                risk_manager=risk_manager,
            )

            notifier = None
            if settings.telegram_bot_token and settings.telegram_chat_id:
                notifier = TelegramNotifier(
                    token=settings.telegram_bot_token,
                    chat_id=settings.telegram_chat_id,
                    controller=controller,
                )
                logger.info("Telegram bot configured")

            # ponytail: API surfaces one representative exchange in M1.
            app = create_app(repo, exchange=api_exchange, controller=controller)

            if api_host not in ("127.0.0.1", "localhost") and not os.getenv("API_KEY"):
                logger.warning(
                    f"API bound to {api_host} with no API_KEY set — trading controls are "
                    "exposed unauthenticated. Set API_KEY or bind to localhost."
                )
            config = uvicorn.Config(app, host=api_host, port=api_port, log_level="warning")
            server = uvicorn.Server(config)
            extra_tasks = []
            supervisor_delay = float(os.getenv("SUPERVISOR_RESTART_DELAY_SECONDS", "5"))
            if notifier:
                extra_tasks.append(run_supervised(
                    name="telegram",
                    task_factory=lambda: _run_notifier_forever(notifier),
                    logger=logger,
                    restart_delay=supervisor_delay,
                ))
                extra_tasks.append(run_supervised(
                    name="reports",
                    task_factory=lambda: run_report_scheduler(notifier=notifier, repo=repo),
                    logger=logger,
                    notifier=notifier,
                    restart_delay=supervisor_delay,
                ))

            # Supervisors restart tasks that fail or return unexpectedly, so a single
            # runtime failure does not take the other runtime surfaces down with it.
            await asyncio.gather(
                *[
                    run_supervised(
                        name=f"trading:{spec.config.loop_id}",
                        task_factory=lambda spec=spec: run_trading_loop(
                            exchange=spec.exchange,
                            paper_mode=paper_mode,
                            strategy=spec.strategy,
                            symbol=spec.symbol,
                            timeframe=spec.timeframe,
                            risk_manager=risk_manager,
                            engine=spec.engine,
                            repo=repo,
                            drift_detector=drift_detector,
                            retrainer=retrainer,
                            notifier=notifier,
                            logger=logger,
                            strategy_filter=spec.strategy_filter,
                            arbiter_mode=spec.config.arbiter_mode,
                        ),
                        logger=logger,
                        notifier=notifier,
                        restart_delay=supervisor_delay,
                    )
                    for spec in loop_specs
                ],
                run_supervised(
                    name="api",
                    task_factory=server.serve,
                    logger=logger,
                    notifier=notifier,
                    restart_delay=supervisor_delay,
                ),
                *extra_tasks,
                return_exceptions=True,
            )
    finally:
        if exchange is not None:
            await _close_if_supported(exchange, logger, "exchange")


if __name__ == "__main__":
    asyncio.run(run())
