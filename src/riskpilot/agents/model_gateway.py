"""Provider-neutral contracts for non-deterministic model calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ModelRequest:
    task: str
    instructions: str
    input_text: str
    prompt_version: str
    max_output_tokens: int = 1200

    def __post_init__(self) -> None:
        if not self.task.strip() or not self.instructions.strip() or not self.input_text.strip():
            raise ValueError("task, instructions, and input_text must not be empty")
        if not self.prompt_version.strip():
            raise ValueError("prompt_version must not be empty")
        if self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")


@dataclass(frozen=True, slots=True)
class ModelResult:
    success: bool
    text: str
    mode: str
    provider: str | None
    model: str | None
    prompt_version: str
    response_id: str | None = None
    usage: Mapping[str, int] | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.success and (not self.text.strip() or self.error_code is not None):
            raise ValueError("successful model result requires text and no error")
        if not self.success and not self.error_code:
            raise ValueError("failed model result requires error_code")


@runtime_checkable
class ModelGateway(Protocol):
    def generate(self, request: ModelRequest) -> ModelResult: ...


@dataclass(frozen=True, slots=True)
class OfflineModelGateway:
    """Fail closed when no model is configured; never imitate live AI output."""

    notice: str = "AI解释当前不可用；风险计算、历史回放和评分功能不受影响。"

    def generate(self, request: ModelRequest) -> ModelResult:
        return ModelResult(
            success=False,
            text=self.notice,
            mode="offline",
            provider=None,
            model=None,
            prompt_version=request.prompt_version,
            error_code="model_offline",
        )

