class AllocationManager:
    def __init__(self, allocations: dict[str, float | None]):
        if not allocations:
            self._allocations = {}
            return

        explicit = {k: v for k, v in allocations.items() if v is not None}
        if explicit:
            total = sum(explicit.values())
            if total > 1.0 + 1e-9:
                raise ValueError("Total allocation cannot exceed 100%")
            remaining = max(0.0, 1.0 - total)
            unset = [k for k, v in allocations.items() if v is None]
            fill = remaining / len(unset) if unset else 0.0
            self._allocations = {
                k: (v if v is not None else fill)
                for k, v in allocations.items()
            }
        else:
            equal = 1.0 / len(allocations)
            self._allocations = {k: equal for k in allocations}

    def allocation_for(self, loop_id: str) -> float:
        return self._allocations[loop_id]

    def scoped_balance(self, loop_id: str, balance: dict[str, float]) -> dict[str, float]:
        scoped = dict(balance)
        if "USDT" in scoped:
            scoped["USDT"] = scoped["USDT"] * self.allocation_for(loop_id)
        return scoped
