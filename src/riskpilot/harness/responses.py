"""Transport-neutral response and error contracts for Harness tools."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Generic, Mapping, TypeVar

DataT = TypeVar("DataT")


@dataclass(frozen=True, slots=True)
class ErrorDetail:
    code: str
    message: str
    retryable: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolMeta:
    tool_name: str
    tool_version: str
    rule_version: str
    trace_id: str
    snapshot_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolResponse(Generic[DataT]):
    """Uniform result envelope used by every Harness tool."""

    success: bool
    data: DataT | None
    meta: ToolMeta
    warnings: tuple[str, ...] = ()
    error: ErrorDetail | None = None

    def __post_init__(self) -> None:
        if self.success and self.error is not None:
            raise ValueError("successful response cannot contain an error")
        if not self.success and self.error is None:
            raise ValueError("failed response must contain an error")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

