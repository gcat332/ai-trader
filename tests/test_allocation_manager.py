import pytest

from core.allocation import AllocationManager


def test_equal_allocation_when_no_explicit_percentages():
    manager = AllocationManager({"loop1": None, "loop2": None})
    assert manager.allocation_for("loop1") == pytest.approx(0.5)
    assert manager.allocation_for("loop2") == pytest.approx(0.5)


def test_explicit_allocation_is_preserved():
    manager = AllocationManager({"loop1": 0.4, "loop2": 0.6})
    assert manager.allocation_for("loop1") == pytest.approx(0.4)
    assert manager.allocation_for("loop2") == pytest.approx(0.6)


def test_allocated_balance_scopes_usdt_without_changing_other_assets():
    manager = AllocationManager({"loop1": 0.4})
    scoped = manager.scoped_balance("loop1", {"USDT": 10000.0, "BTC": 1.0})
    assert scoped["USDT"] == pytest.approx(4000.0)
    assert scoped["BTC"] == pytest.approx(1.0)


def test_invalid_total_allocation_rejected():
    with pytest.raises(ValueError):
        AllocationManager({"loop1": 0.8, "loop2": 0.8})


def test_allocation_scoped_balance_preserves_existing_position_formula():
    manager = AllocationManager({"loop1": 0.4})
    balance = manager.scoped_balance("loop1", {"USDT": 10000.0})
    assert balance["USDT"] == pytest.approx(4000.0)
