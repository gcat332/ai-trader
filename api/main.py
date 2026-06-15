# api/main.py
import asyncio
import json
import os
from datetime import date
from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from db.repository import Repository
from api import bus


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Gate on the API_KEY env var. When set, mutating control endpoints require a
    matching X-API-Key header. When unset, control is allowed (the server should be
    bound to localhost in that case — see API_HOST in main.py)."""
    expected = os.getenv("API_KEY", "")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def create_app(repo: Repository, exchange=None, controller=None) -> FastAPI:
    app = FastAPI(title="AI Trader API")
    # Default to local dashboard dev origins, not "*" — the API exposes financial
    # data and trading controls. Override with CORS_ORIGINS for other origins.
    origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
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

    @app.get("/api/strategies")
    async def get_strategies():
        # Report the real engine state, not a hardcoded placeholder. Without a
        # controller (read-only API server) status is genuinely unknown.
        if controller is None:
            return [{"id": "unknown", "status": "unknown"}]
        status = await controller.get_status()
        return [{
            "id": status.get("strategy_id", "unknown"),
            "status": "running" if status.get("running") else "stopped",
        }]

    @app.post("/api/strategies/{strategy_id}/start", dependencies=[Depends(require_api_key)])
    async def start_strategy(strategy_id: str):
        if controller is None:
            raise HTTPException(status_code=503, detail="Engine control not available on this server")
        await controller.resume()
        return {"id": strategy_id, "status": "running"}

    @app.post("/api/strategies/{strategy_id}/stop", dependencies=[Depends(require_api_key)])
    async def stop_strategy(strategy_id: str):
        if controller is None:
            raise HTTPException(status_code=503, detail="Engine control not available on this server")
        await controller.pause()
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
        # Not yet wired to BacktestRunner. Return an honest 501 rather than a fake
        # "queued" placeholder that misleads the operator into thinking a run started.
        raise HTTPException(status_code=501, detail="Backtest trigger not implemented; run via CLI")

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

    @app.websocket("/ws/feed")
    async def websocket_feed(websocket: WebSocket):
        await websocket.accept()
        q = bus.subscribe()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30.0)
                    await websocket.send_text(json.dumps(event))
                except asyncio.TimeoutError:
                    # Send a heartbeat to keep the connection alive
                    await websocket.send_text(json.dumps({"type": "heartbeat"}))
                    continue
        except WebSocketDisconnect:
            pass
        finally:
            bus.unsubscribe(q)

    return app
