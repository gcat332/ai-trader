# backtest/runner.py
from core.models import TradeRecord
from exchange.paper import PaperExchange
from risk.manager import RiskManager
from strategy.base import BaseStrategy
from core.engine import Engine


class BacktestRunner:

    def __init__(
        self,
        strategy: BaseStrategy,
        risk_manager: RiskManager,
        initial_balance: dict[str, float],
        symbol: str,
        timeframe: str = "1h",
        repo=None,
    ):
        self._strategy = strategy
        self._risk_manager = risk_manager
        self._initial_balance = initial_balance
        self._symbol = symbol
        self._timeframe = timeframe
        self._repo = repo

    async def run(self, candles: list[list]) -> list[TradeRecord]:
        """
        Replay candles sequentially.
        Each candle: run engine (signal → risk → order), then tick exchange for TP/SL.
        Returns list of completed TradeRecords.
        """
        exchange = PaperExchange(initial_balance=dict(self._initial_balance))
        engine = Engine(
            exchange=exchange,
            strategy=self._strategy,
            symbol=self._symbol,
            timeframe=self._timeframe,
            risk_manager=self._risk_manager,
            repo=self._repo,
        )

        for i, candle in enumerate(candles):
            window = candles[max(0, i - 249): i + 1]  # 250 candles: enough to warm up EMA200 (trend_pullback)
            await engine.process_candles(window)

            _, high, low, close = candle[1], candle[2], candle[3], candle[4]
            fills = await exchange.tick(self._symbol, high=high, low=low, close=close)
            if fills:
                # tick may close several positions (one per strategy) in one candle;
                # record each newly-logged TradeRecord for outcome tracking.
                for trade in exchange.get_trade_log()[-len(fills):]:
                    await engine.record_trade_outcome(trade)

        return exchange.get_trade_log()
