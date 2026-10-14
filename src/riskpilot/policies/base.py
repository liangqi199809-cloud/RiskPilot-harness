"""Policy interface for authorization, compliance, and time boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from riskpilot.harness.context import RuntimeContext
from riskpilot.harness.responses import ToolResponse


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason: str | None = None
    warnings: tuple[str, ...] = ()


@runtime_checkable
class PolicyGuard(Protocol):
    def before_call(self, context: RuntimeContext, tool_name: str, arguments: dict[str, Any]) -> PolicyDecision: ...

    def after_call(self, context: RuntimeContext, tool_name: str, response: ToolResponse[Any]) -> PolicyDecision: ...

