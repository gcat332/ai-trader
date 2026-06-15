# tests/test_claude_arbiter.py
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.claude_arbiter import ClaudeStrategyArbiter
from core.strategy_arbiter import StrategyArbiter

STRATEGIES = ["rsi_macd", "bollinger", "ema"]


def _tool_use(name, inp, tid="t1"):
    return SimpleNamespace(type="tool_use", name=name, input=inp, id=tid)


def _resp(*blocks):
    return SimpleNamespace(content=list(blocks))


def _arbiter(client):
    fallback = StrategyArbiter(strategies=STRATEGIES, epsilon=0.0)
    repo = AsyncMock()
    repo.get_decisions.return_value = [{"decision": "BUY", "outcome": "WIN"}]
    repo.get_ab_test_history.return_value = []
    return ClaudeStrategyArbiter(STRATEGIES, fallback, repo, client=client), repo


@pytest.mark.asyncio
async def test_submit_decision_returns_switch():
    client = MagicMock()
    client.messages.create.return_value = _resp(
        _tool_use("submit_decision",
                  {"decision": "SWAP", "to_strategy": "bollinger", "reason": "sideways favors BB"})
    )
    arb, _ = _arbiter(client)
    sw = await arb.decide("sideways", "rsi_macd", [])
    assert sw.decision == "SWAP"
    assert sw.to_strategy == "bollinger"
    assert sw.from_strategy == "rsi_macd"
    assert sw.reason.startswith("[claude]")


@pytest.mark.asyncio
async def test_tool_call_then_decision():
    client = MagicMock()
    client.messages.create.side_effect = [
        _resp(_tool_use("get_recent_decisions", {"limit": 10})),
        _resp(_tool_use("submit_decision",
                        {"decision": "HOLD_COURSE", "to_strategy": "rsi_macd", "reason": "stable"})),
    ]
    arb, repo = _arbiter(client)
    sw = await arb.decide("trending", "rsi_macd", [])
    assert sw.decision == "HOLD_COURSE"
    assert sw.reason.startswith("[claude]")
    repo.get_decisions.assert_awaited_once()
    assert client.messages.create.call_count == 2


@pytest.mark.asyncio
async def test_invalid_strategy_falls_back():
    client = MagicMock()
    client.messages.create.return_value = _resp(
        _tool_use("submit_decision",
                  {"decision": "SWAP", "to_strategy": "nonexistent", "reason": "bogus"})
    )
    arb, _ = _arbiter(client)
    sw = await arb.decide("sideways", "rsi_macd", [])
    assert "[claude]" not in sw.reason


@pytest.mark.asyncio
async def test_api_exception_falls_back():
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("api down")
    arb, _ = _arbiter(client)
    sw = await arb.decide("sideways", "rsi_macd", [])
    assert "[claude]" not in sw.reason
    assert sw.decision in ("SWAP", "RETRAIN", "EXPLORE", "HOLD_COURSE")


@pytest.mark.asyncio
async def test_loop_exhaustion_falls_back():
    client = MagicMock()
    # Always reads, never submits → loop exhausts.
    client.messages.create.return_value = _resp(_tool_use("get_ab_test_history", {}))
    arb, _ = _arbiter(client)
    sw = await arb.decide("sideways", "rsi_macd", [])
    assert "[claude]" not in sw.reason
    assert client.messages.create.call_count == 4
