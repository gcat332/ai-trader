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
    ):
        self._strategy = strategy
        self._risk_manager = risk_manager
        self._initial_balance = initial_balance
        self._symbol = symbol
        self._timeframe = timeframe

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
        )

        for i, candle in enumerate(candles):
            window = candles[max(0, i - 99): i + 1]  # rolling 100-candle window for indicators
            await engine.process_candles(window)

            # Apply TP/SL from the signal to the just-opened position
            positions = await exchange.get_positions()
            for pos in positions:
                if pos.take_profit is None and pos.stop_loss is None:
                    pass  # already set by strategy via set_position_tp_sl or default

            _, high, low, close = candle[1], candle[2], candle[3], candle[4]
            await exchange.tick(self._symbol, high=high, low=low, close=close)

        return exchange.get_trade_log()
