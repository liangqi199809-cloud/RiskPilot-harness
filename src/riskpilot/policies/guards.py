"""Concrete policy guards for product isolation and evidence boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from riskpilot.harness.context import ProductScenario, RuntimeContext
from riskpilot.harness.responses import ToolResponse
from riskpilot.policies.base import PolicyDecision


CORE_TOOLS = frozenset(
    {
        "calculate_risk_budget", "extract_risk_inputs", "get_visible_snapshot",
        "verify_evidence", "draw_history_case", "get_replay_session", "preview_replay_position",
        "submit_replay_action", "submit_replay_score", "get_leaderboard",
    }
)

DEFAULT_SCENARIO_TOOLS: Mapping[ProductScenario, frozenset[str]] = {
    ProductScenario.CONSUMER_EDUCATION: CORE_TOOLS,
    ProductScenario.INSTITUTION_TRAINING: CORE_TOOLS,
    ProductScenario.RESEARCH_SANDBOX: CORE_TOOLS,
    ProductScenario.PORTFOLIO_DEMO: frozenset(
        {"calculate_risk_budget", "extract_risk_inputs", "get_visible_snapshot", "verify_evidence", "get_leaderboard"}
    ),
}


@dataclass(frozen=True, slots=True)
class ScenarioToolPolicy:
    """Keep write-capable game tools out of read-only product scenarios."""

    allowed_tools: Mapping[ProductScenario, frozenset[str]] = field(
        default_factory=lambda: DEFAULT_SCENARIO_TOOLS
    )

    def before_call(self, context: RuntimeContext, tool_name: str, arguments: dict[str, Any]) -> PolicyDecision:
        allowed = self.allowed_tools.get(context.scenario, frozenset())
        if tool_name not in allowed:
            return PolicyDecision(False, f"tool {tool_name} is not allowed in scenario {context.scenario.value}")
        return PolicyDecision(True)

    def after_call(self, context: RuntimeContext, tool_name: str, response: ToolResponse[Any]) -> PolicyDecision:
        return PolicyDecision(True)


@dataclass(frozen=True, slots=True)
class SnapshotRequiredPolicy:
    """Require direct calculations to declare the evidence snapshot they use."""

    protected_tools: frozenset[str] = frozenset({"calculate_risk_budget"})

    def before_call(self, context: RuntimeContext, tool_name: str, arguments: dict[str, Any]) -> PolicyDecision:
        if tool_name in self.protected_tools and not context.snapshot_id:
            return PolicyDecision(False, f"tool {tool_name} requires snapshot_id")
        return PolicyDecision(True)

    def after_call(self, context: RuntimeContext, tool_name: str, response: ToolResponse[Any]) -> PolicyDecision:
        return PolicyDecision(True)

