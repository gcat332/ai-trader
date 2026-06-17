import uuid


class OrderIntentStore:
    def __init__(self) -> None:
        self._ids: dict[tuple[str, str, str], str] = {}

    def intent_id(self, strategy_instance_id: str, symbol: str, decision_id: str) -> str:
        key = (strategy_instance_id, symbol, decision_id)
        if key not in self._ids:
            self._ids[key] = str(uuid.uuid5(uuid.NAMESPACE_URL, "|".join(key)))
        return self._ids[key]
