from core.strategy_manager import StrategyManager


class StrategyLifecycleController:
    def __init__(self, manager: StrategyManager):
        self._manager = manager

    async def start_bot(self) -> None:
        self._manager.start_all()

    async def stop_bot(self) -> None:
        self._manager.stop_all()

    async def restart_bot(self) -> None:
        self._manager.restart_all()

    async def start_strategy(self, loop_id: str) -> None:
        self._manager.start(loop_id)

    async def stop_strategy(self, loop_id: str) -> None:
        self._manager.stop(loop_id)
