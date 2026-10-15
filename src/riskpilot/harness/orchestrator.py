"""The single governed execution path for all Harness tools."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from time import perf_counter
from typing import Any, Iterable

from riskpilot.harness.context import RuntimeContext
from riskpilot.harness.registry import ToolNotFoundError, ToolRegistry
from riskpilot.harness.responses import ErrorDetail, ToolMeta, ToolResponse
from riskpilot.infrastructure.audit_store import AuditRecorder
from riskpilot.policies.base import PolicyGuard

POLICY_RULE_VERSION = "harness-policy-v1"


def _digest(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False, default=str,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


class HarnessOrchestrator:
    """Apply policies, invoke exactly one registered tool, and audit the result."""

    def __init__(
        self,
        registry: ToolRegistry,
        policies: Iterable[PolicyGuard] = (),
        audit_recorder: AuditRecorder | None = None,
    ) -> None:
        self.registry = registry
        self.policies = tuple(policies)
        self.audit_recorder = audit_recorder

    @staticmethod
    def _failure(context: RuntimeContext, tool_name: str, tool_version: str, code: str, message: str) -> ToolResponse[Any]:
        return ToolResponse(
            success=False,
            data=None,
            meta=ToolMeta(
                tool_name=tool_name, tool_version=tool_version,
                rule_version=POLICY_RULE_VERSION, trace_id=context.trace_id,
                snapshot_id=context.snapshot_id,
            ),
            error=ErrorDetail(code=code, message=message),
        )

    def invoke(
        self, tool_name: str, context: RuntimeContext,
        arguments: dict[str, Any] | None = None,
    ) -> ToolResponse[Any]:
        supplied_arguments = dict(arguments or {})
        started = perf_counter()
        try:
            tool = self.registry.get(tool_name)
            tool_version = tool.version
        except ToolNotFoundError as exc:
            tool = None
            tool_version = "unregistered"
            response = self._failure(context, tool_name, tool_version, "tool_not_found", str(exc))
        else:
            warnings: list[str] = []
            response = None
            for policy in self.policies:
                decision = policy.before_call(context, tool_name, supplied_arguments)
                warnings.extend(decision.warnings)
                if not decision.allowed:
                    response = self._failure(
                        context, tool_name, tool_version, "policy_denied",
                        decision.reason or "tool call denied by policy",
                    )
                    break
            if response is None:
                try:
                    response = tool.invoke(context, supplied_arguments)
                except Exception:  # Boundary: tools must not leak runtime failures to clients.
                    response = self._failure(
                        context, tool_name, tool_version, "tool_execution_failed",
                        "tool execution failed",
                    )
            for policy in self.policies:
                decision = policy.after_call(context, tool_name, response)
                warnings.extend(decision.warnings)
                if not decision.allowed:
                    response = self._failure(
                        context, tool_name, tool_version, "policy_denied",
                        decision.reason or "tool result denied by policy",
                    )
                    break
            if warnings:
                response = replace(response, warnings=(*response.warnings, *warnings))

        if self.audit_recorder is not None:
            self.audit_recorder.record(
                context=context,
                tool_name=tool_name,
                input_sha256=_digest(supplied_arguments),
                output_sha256=_digest(response.to_dict()),
                response=response,
                duration_ms=(perf_counter() - started) * 1000,
            )
        return response

