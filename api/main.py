import os
from datetime import date
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from db.repository import Repository


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Gate on the API_KEY env var. When set, mutating control endpoints require a
    matching X-API-Key header. When unset, control is allowed (the server should be
    bound to localhost in that case — see API_HOST in main.py)."""
    expected = os.getenv("API_KEY", "")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def create_app(repo: Repository, exchange=None, controller=None) -> FastAPI:
    app = FastAPI(title="AI Trader API")
    # CORS is opt-in because the API exposes financial data and trading controls.
    origins = [o for o in os.getenv("CORS_ORIGINS", "").split(",") if o]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get("/api/positions")
    async def get_positions():
        if exchange is not None:
            positions = await exchange.get_positions()
            return [
                {
                    "symbol": p.symbol,
                    "side": p.side,
                    "entry_price": p.entry_price,
                    "quantity": p.quantity,
                    "unrealized_pnl": p.unrealized_pnl,
                    "mode": p.mode,
                }
                for p in positions
            ]
        return await repo.get_trade_history()  # fallback: closed trade history

    @app.get("/api/orders")
    async def get_orders(symbol: str | None = None):
        return await repo.get_orders(symbol=symbol)

    @app.get("/api/pnl")
    async def get_pnl():
        trades = await repo.get_trade_history()
        total = sum(t.get("realized_pnl", 0) or 0 for t in trades)
        today_trades = [t for t in trades if t.get("exit_time", "")[:10] == date.today().isoformat()]
        daily = sum(t.get("realized_pnl", 0) or 0 for t in today_trades)
        return {"total": total, "daily": daily}

    @app.get("/api/health")
    async def health():
        # Liveness/readiness for an external monitor (uptime check, systemd, etc).
        # last_decision_at is the freshest proxy for "the trading loop is ticking".
        out: dict = {"status": "ok"}
        if controller is not None:
            st = await controller.get_status()
            out["engine_running"] = st.get("running")
            out["active_strategy"] = st.get("strategy_id")
            out["open_positions"] = len(st.get("open_positions") or [])
        else:
            out["engine_running"] = None  # read-only API server, no engine attached
        recent = await repo.get_decisions(limit=1)
        out["last_decision_at"] = recent[0]["timestamp"] if recent else None
        return out

    @app.get("/api/strategies")
    async def get_strategies():
        # Report the real loop-level runtime state. Without a controller
        # (read-only API server) status is genuinely unknown.
        if controller is None:
            return [{"id": "unknown", "status": "unknown", "active": False}]
        return await controller.get_strategies()

    @app.get("/api/strategies/available")
    async def get_available_strategies():
        from core.strategy_registry import StrategyRegistry
        return StrategyRegistry().available()

    @app.post("/api/strategies/{strategy_id}/start", dependencies=[Depends(require_api_key)])
    async def start_strategy(strategy_id: str):
        if controller is None:
            raise HTTPException(status_code=503, detail="Engine control not available on this server")
        try:
            await controller.start_strategy(strategy_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc).strip("'")) from None
        return {"id": strategy_id, "status": "running"}

    @app.post("/api/strategies/{strategy_id}/stop", dependencies=[Depends(require_api_key)])
    async def stop_strategy(strategy_id: str):
        if controller is None:
            raise HTTPException(status_code=503, detail="Engine control not available on this server")
        try:
            await controller.stop_strategy(strategy_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc).strip("'")) from None
        return {"id": strategy_id, "status": "stopped"}

    @app.get("/api/trades/history")
    async def get_trade_history(
        symbol: str | None = None,
        strategy_id: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
    ):
        return await repo.get_trade_history(
            symbol=symbol, strategy_id=strategy_id,
            from_date=from_date, to_date=to_date,
        )

    @app.get("/api/backtest/history")
    async def get_backtest_history():
        return await repo.get_backtest_history()

    @app.get("/api/backtest/{run_id}")
    async def get_backtest_run(run_id: str):
        run = await repo.get_backtest_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Backtest run not found")
        return run

    @app.post("/api/backtest/run", dependencies=[Depends(require_api_key)])
    async def trigger_backtest(body: dict):
        import uuid
        from datetime import datetime, timezone
        from backtest.runner import BacktestRunner
        from backtest.reporter import BacktestReporter
        from data.fetcher import DataFetcher
        from risk.manager import RiskManager
        from strategy.ml.dummy_model import DummyModel
        from strategy.rsi_macd import RsiMacdStrategy
        from strategy.bollinger_reversion import BollingerReversionStrategy
        from strategy.ema_cross import EmaCrossStrategy
        from strategy.trend_pullback import TrendPullbackStrategy
        from strategy.liquidation_reversion import LiquidationReversionStrategy

        strategy_id = body.get("strategy_id", "rsi_macd")
        symbol = body.get("symbol", "BTC/USDT")
        from_date = body.get("from_date") or ""
        to_date = body.get("to_date") or ""
        timeframe = body.get("timeframe", "1h")

        builders = {
            "rsi_macd": lambda: RsiMacdStrategy(ml_model=DummyModel(0.75)),
            "bollinger_reversion": lambda: BollingerReversionStrategy(ml_model=DummyModel(0.75)),
            "ema_cross": lambda: EmaCrossStrategy(ml_model=DummyModel(0.75)),
            "trend_pullback": lambda: TrendPullbackStrategy(ml_model=DummyModel(0.75)),
            "liquidation_reversion": lambda: LiquidationReversionStrategy(ml_model=DummyModel(0.75)),
        }
        if strategy_id not in builders:
            raise HTTPException(status_code=422,
                detail=f"unknown strategy_id {strategy_id!r}; valid: {list(builders)}")

        # Pull recent candles, then keep only those inside the requested [from, to]
        # window. Data availability is bounded by the configured exchange (testnet
        # holds a limited recent history), so a range outside it yields fewer/no
        # candles — reflected honestly in the result rather than faked.
        fetcher = DataFetcher(exchange_id="binance", testnet=True)
        try:
            candles = await fetcher.fetch_ohlcv(symbol, timeframe, limit=500)
        finally:
            await fetcher.close()

        def _ms(d: str, end: bool) -> int | None:
            if not d:
                return None
            dt = datetime.fromisoformat(d).replace(tzinfo=timezone.utc)
            if end:
                dt = dt.replace(hour=23, minute=59, second=59)
            return int(dt.timestamp() * 1000)

        lo, hi = _ms(from_date, False), _ms(to_date, True)
        if lo is not None:
            candles = [c for c in candles if c[0] >= lo]
        if hi is not None:
            candles = [c for c in candles if c[0] <= hi]

        # on_candle (the CPU-heavy pandas-ta path) is already offloaded to a thread
        # inside engine.process_candles (engine.py:157), so this replay yields the
        # event loop every candle and does not block the live trading loop.
        runner = BacktestRunner(
            strategy=builders[strategy_id](), risk_manager=RiskManager(),
            initial_balance={"USDT": 10000.0}, symbol=symbol, timeframe=timeframe,
        )
        trades = await runner.run(candles)
        stats = BacktestReporter(trades).compute()

        run_id = str(uuid.uuid4())
        await repo.insert_backtest_run(run_id, strategy_id, symbol, from_date, to_date, stats)
        return {"run_id": run_id, "candles": len(candles), **stats}

    @app.get("/api/compare")
    async def compare(strategy: str, from_date: str | None = None, to_date: str | None = None):
        live = await repo.get_trade_history(strategy_id=strategy, from_date=from_date, to_date=to_date)
        backtest = await repo.get_backtest_history()
        return {"live_trades": live, "backtest_runs": backtest}

    @app.get("/api/decisions")
    async def get_decisions(
        symbol: str | None = None,
        limit: int = 50,
    ):
        rows = await repo.get_decisions(symbol=symbol, limit=limit)
        return {"decisions": rows}

    @app.get("/api/decisions/metrics")
    async def get_decision_metrics(limit: int = 30):
        metrics = await repo.get_decision_metrics(limit=limit)
        return metrics

    @app.get("/api/health/strategy")
    async def get_strategy_health():
        metrics = await repo.get_decision_metrics(limit=30)
        from core.drift_monitor import DriftDetector
        detector = DriftDetector()
        calibration = await detector._compute_calibration(repo)
        return {
            "win_rate_30": metrics["win_rate"],
            "total_outcomes": metrics["total"],
            "avg_pnl": metrics["avg_pnl"],
            "confidence_calibration": calibration,
        }

    @app.get("/api/ab-tests")
    async def get_ab_tests(limit: int = 20):
        return await repo.get_ab_test_history(limit=limit)

    @app.get("/api/strategy-profiles")
    async def get_strategy_profiles():
        return await repo.get_strategy_profiles()

    @app.get("/api/strategy-switches")
    async def get_strategy_switches(limit: int = 50):
        return await repo.get_strategy_switches(limit=limit)

    return app
