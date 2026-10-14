"""Tool interface and registry used by the Harness orchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from riskpilot.harness.context import RuntimeContext
from riskpilot.harness.responses import ToolResponse


class DuplicateToolError(ValueError):
    pass


class ToolNotFoundError(LookupError):
    pass


@runtime_checkable
class Tool(Protocol):
    name: str
    version: str

    def invoke(self, context: RuntimeContext, arguments: dict[str, Any]) -> ToolResponse[Any]: ...


@dataclass(slots=True)
class ToolRegistry:
    _tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        if not isinstance(tool, Tool):
            raise TypeError("tool must implement the Tool protocol")
        if not tool.name.strip():
            raise ValueError("tool name must not be empty")
        if tool.name in self._tools:
            raise DuplicateToolError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"tool not registered: {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def invoke(self, name: str, context: RuntimeContext, arguments: dict[str, Any] | None = None) -> ToolResponse[Any]:
        return self.get(name).invoke(context, dict(arguments or {}))

