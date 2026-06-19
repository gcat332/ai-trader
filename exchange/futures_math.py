"""Pure isolated-margin, one-way futures math. No I/O.
# ponytail: simplified — ignores Binance tiered maintenance margin and funding.
# Upgrade to the tier table if paper/live liquidation prices diverge materially."""


def liquidation_price(side: str, entry: float, leverage: int, mmr: float = 0.005) -> float:
    # Isolated one-way approximation. Long liquidates as price falls, short as it rises.
    if leverage <= 0:
        raise ValueError("leverage must be >= 1")
    if side.upper() == "LONG":
        return entry * (1 - 1 / leverage + mmr)
    return entry * (1 + 1 / leverage - mmr)


def realized_pnl(side: str, entry: float, exit: float, quantity: float) -> float:
    direction = 1.0 if side.upper() == "LONG" else -1.0
    return direction * (exit - entry) * quantity
