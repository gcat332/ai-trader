from exchange.futures_math import liquidation_price, realized_pnl


def test_mmr_default_is_single_source_of_truth():
    from exchange.futures_math import MMR_DEFAULT
    import inspect
    from risk.manager import RiskManager
    from exchange.paper_futures import PaperFuturesExchange
    assert MMR_DEFAULT == 0.005
    # the literal 0.005 must no longer be hard-coded as a default in the consumers
    assert inspect.signature(RiskManager.evaluate).parameters["mmr"].default == MMR_DEFAULT
    assert inspect.signature(PaperFuturesExchange.__init__).parameters["mmr"].default == MMR_DEFAULT


def test_long_liquidation_below_entry():
    # 5x long at 100, mmr 0: liq ~ 100*(1 - 1/5) = 80
    assert liquidation_price("LONG", 100.0, 5, mmr=0.0) == 80.0

def test_short_liquidation_above_entry():
    # 5x short at 100, mmr 0: liq ~ 100*(1 + 1/5) = 120
    assert liquidation_price("SHORT", 100.0, 5, mmr=0.0) == 120.0

def test_mmr_widens_long_liquidation_upward():
    # mmr makes liq closer to entry (hit sooner) for longs -> higher than the mmr=0 case
    assert liquidation_price("LONG", 100.0, 5, mmr=0.005) > 80.0

def test_pnl_long_and_short_signs():
    assert realized_pnl("LONG", 100.0, 110.0, 2.0) == 20.0
    assert realized_pnl("SHORT", 100.0, 110.0, 2.0) == -20.0
    assert realized_pnl("SHORT", 100.0, 90.0, 2.0) == 20.0
