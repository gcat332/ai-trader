# core/claude_arbiter.py
import os
import uuid
from datetime import datetime, timezone

from core.models import StrategySwitch

_TOOLS = [
    {
        "name": "get_recent_decisions",
        "description": "Recent strategy decisions and their outcomes (win/loss, pnl, regime).",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
            "required": [],
        },
    },
    {
        "name": "get_ab_test_history",
        "description": "Recent champion-vs-challenger A/B test results.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "submit_decision",
        "description": "Submit the final arbitration decision. Terminal — call once you are done.",
        "input_schema": {
            "type": "object",
            "properties": {
                "decision": {"type": "string", "enum": ["SWAP", "RETRAIN", "EXPLORE", "HOLD_COURSE"]},
                "to_strategy": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["decision", "to_strategy", "reason"],
        },
    },
]

_DECISIONS = {"SWAP", "RETRAIN", "EXPLORE", "HOLD_COURSE"}


class ClaudeStrategyArbiter:
    """Agent-based (tool-use) arbiter for multi mode.

    Runs a manual Anthropic tool-use loop: Claude may read recent decisions / A/B
    history, then calls submit_decision. The rule-based StrategyArbiter is the safe
    fallback — decide() NEVER raises and ALWAYS returns a StrategySwitch.

    ponytail: sync client blocks the loop, but the arbiter only runs on drift ticks
    (infrequent); switch to AsyncAnthropic if it ever runs per-candle.
    """

    def __init__(self, strategies, fallback, repo, client=None, model=None, max_iterations=4):
        self._strategies = strategies
        self._fallback = fallback
        self._repo = repo
        if client is not None:
            self._client = client
        else:
            import anthropic
            self._client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self._model = model or os.getenv("CLAUDE_ARBITER_MODEL", "claude-opus-4-8")
        self._max_iterations = max_iterations

    async def decide(self, regime, active, profiles) -> StrategySwitch:
        try:
            return await self._decide(regime, active, profiles)
        except Exception:
            return self._fallback.decide(regime, active, profiles)

    async def _decide(self, regime, active, profiles) -> StrategySwitch:
        system = (
            "You are a trading-strategy arbiter. Given the current market regime, the "
            "active strategy, and per-(strategy, regime) win-rate profiles, decide whether "
            "to SWAP to a better technique, RETRAIN the active model, EXPLORE an under-sampled "
            "technique, or HOLD_COURSE. Use the read-only tools if you need more evidence, "
            "then call submit_decision exactly once. to_strategy must be one of: "
            f"{', '.join(self._strategies)}."
        )
        messages = [{
            "role": "user",
            "content": (
                f"regime={regime}\nactive={active}\navailable={self._strategies}\n"
                f"profiles={profiles}"
            ),
        }]

        for _ in range(self._max_iterations):
            resp = self._client.messages.create(
                model=self._model, max_tokens=1024, system=system,
                messages=messages, tools=_TOOLS,
            )
            tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
            if not tool_uses:
                break  # end_turn without a decision → fall back

            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for tu in tool_uses:
                if tu.name == "submit_decision":
                    return self._finalize(regime, active, profiles, tu.input)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": await self._run_tool(tu.name, tu.input),
                })
            messages.append({"role": "user", "content": results})

        return self._fallback.decide(regime, active, profiles)

    async def _run_tool(self, name, inp) -> str:
        if name == "get_recent_decisions":
            return str(await self._repo.get_decisions(limit=int(inp.get("limit", 30))))
        if name == "get_ab_test_history":
            return str(await self._repo.get_ab_test_history(limit=20))
        return f"unknown tool: {name}"

    def _finalize(self, regime, active, profiles, inp) -> StrategySwitch:
        decision = inp.get("decision")
        to_strategy = inp.get("to_strategy")
        reason = (inp.get("reason") or "").strip()
        if decision not in _DECISIONS or to_strategy not in self._strategies or not reason:
            return self._fallback.decide(regime, active, profiles)
        return StrategySwitch(
            id=str(uuid.uuid4())[:8], timestamp=datetime.now(timezone.utc),
            regime=regime, from_strategy=active, to_strategy=to_strategy,
            decision=decision, reason=f"[claude] {reason}",
        )
