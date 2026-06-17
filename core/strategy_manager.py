class StrategyManager:
    def __init__(self, runtimes: list):
        self._runtimes = {r.config.loop_id: r for r in runtimes}

    def runtimes(self) -> list:
        return list(self._runtimes.values())

    def loop_ids(self) -> list[str]:
        return list(self._runtimes)

    def get(self, loop_id: str):
        try:
            return self._runtimes[loop_id]
        except KeyError:
            valid = ", ".join(self.loop_ids())
            raise KeyError(f"Unknown loop_id {loop_id!r}. Valid: {valid}") from None

    def start(self, loop_id: str) -> None:
        self.get(loop_id).engine.is_running = True

    def stop(self, loop_id: str) -> None:
        self.get(loop_id).engine.is_running = False

    def restart(self, loop_id: str) -> None:
        runtime = self.get(loop_id)
        runtime.engine.is_running = False
        runtime.engine.is_running = True

    def start_all(self) -> None:
        for runtime in self.runtimes():
            runtime.engine.is_running = True

    def stop_all(self) -> None:
        for runtime in self.runtimes():
            runtime.engine.is_running = False

    def restart_all(self) -> None:
        for runtime in self.runtimes():
            runtime.engine.is_running = False
        for runtime in self.runtimes():
            runtime.engine.is_running = True
