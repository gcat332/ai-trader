# core/trading_loop.py
"""The live trading loop. Extracted verbatim from main.py's nested `trading_loop`
so the composition root (main.py) only wires components and the operational loop
can be reasoned about and tested on its own.

The loop is self-healing: the whole body is wrapped so any transient failure
(balance fetch, OHLCV fetch, processing) is caught and counted, and never
propagates an exception that would tear down the gathered uvicorn server."""
import asyncio
import os
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from core.live_outcome_tracker import LiveOutcomeTracker
from core.strategy_arbiter import StrategyArbiter
from data.fetcher import DataFetcher
from ml.ab_tester import ModelABTester
from strategy.meta_strategy import MetaStrategy
from strategy.regime import RegimeClassifier


def _cooldown_elapsed(last_retrain_iso: str, days: int) -> bool:
    last = datetime.fromisoformat(last_retrain_iso)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last) >= timedelta(days=days)


async def _handle_daily_reset(*, exchange, risk_manager, last_reset_date, today: date | None = None):
    today = today or date.today()
    if today == last_reset_date:
        return last_reset_date
    bal = await exchange.get_balance()
    risk_manager.reset_daily(bal.get("USDT", 0.0))
    return today


async def run_trading_loop(
    *,
    exchange,
    paper_mode: bool,
    strategy,
    symbol: str,
    timeframe: str,
    risk_manager,
    engine,
    repo,
    drift_detector,
    retrainer,
    notifier,
    logger,
    strategy_filter: str | None = None,
) -> None:
    # Single data source. Live: reuse the trading exchange's ccxt client so
    # candle fetches and order/balance calls share ONE connection and rate
    # limiter (no second client silently racing the limit). Paper: the
    # PaperExchange can't fetch, so use a real-market DataFetcher.
    data_source = exchange if not paper_mode else DataFetcher(
        exchange_id="binance", testnet=True,
    )
    last_reset_date = None
    consecutive_failures = 0
    drift_tick = 0

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
            # Daily reset only updates risk baselines. Scheduled reports are owned
            # by scheduler.reports so multi-loop runtimes do not send duplicates.
            last_reset_date = await _handle_daily_reset(
                exchange=exchange,
                risk_manager=risk_manager,
                last_reset_date=last_reset_date,
            )

            if engine.is_running:
                candles = await data_source.fetch_ohlcv(symbol, timeframe, limit=250)  # 250: warms up EMA200 (trend_pullback)
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

                # Record live trade closes so drift profiles, PnL, and Trade
                # History have real data — in EVERY strategy mode, not just multi.
                # A stop/TP fill shrinks the spot balance; detect_closed diffs
                # snapshots to synthesize the closed TradeRecord.
                # When two loops share one exchange (plan B/C), each loop only owns
                # its own strategy's positions — filter so this loop records only its
                # closes and never consumes the other loop's positions.
                def _mine(positions):
                    if strategy_filter is None:
                        return positions
                    return [p for p in positions if p.strategy_id == strategy_filter]

                positions_now = _mine(await exchange.get_positions())
                for trade in outcome_tracker.detect_closed(positions_now, last_close):
                    await engine.record_trade_outcome(trade)  # stamps trade.strategy_id
                    await repo.insert_trade(trade)  # persist to live trade log (Trade History/Compare)
                outcome_tracker.snapshot(_mine(await exchange.get_positions()))

                # Drift check every N candles (configurable via DRIFT_CHECK_INTERVAL env var)
                drift_tick += 1

                drift_interval = int(os.getenv("DRIFT_CHECK_INTERVAL", "10"))

                if isinstance(strategy, MetaStrategy):
                    # Regime-aware arbitration replaces the Phase-9 retrain block
                    # when running in multi mode.
                    if drift_tick % drift_interval == 0:
                        event = await drift_detector.check(repo)
                        if event is not None:
                            if notifier:
                                await notifier.send_drift_alert(event)
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
                    if engine._ab_tester is not None and drift_tick % drift_interval == 0:
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

                    if drift_tick % drift_interval == 0:
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
            loop_errored = False
        except Exception as e:
            loop_errored = True
            consecutive_failures += 1
            logger.error(f"Engine loop error (attempt {consecutive_failures}): {e}")
            if consecutive_failures >= 5 and notifier:
                await notifier.send("⚠️ Data feed lost — 5 consecutive failures, trading paused")
                engine.is_running = False

        # Sleep policy:
        #  - paused: poll fast so /resume takes effect quickly
        #  - errored: short backoff so 5 consecutive failures trip in minutes,
        #    not ~5 hours (sleeping a full candle between failures hid outages)
        #  - healthy: once per closed hourly candle
        if not engine.is_running:
            delay = 10
        elif loop_errored:
            delay = int(os.getenv("ERROR_BACKOFF_SECONDS", "30"))
        else:
            delay = int(os.getenv("LOOP_INTERVAL_SECONDS", "3600"))
        await asyncio.sleep(delay)
