"""Harness tools that enforce historical visibility and evidence integrity."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from riskpilot.harness.context import RuntimeContext
from riskpilot.harness.responses import ErrorDetail, ToolMeta, ToolResponse
from riskpilot.infrastructure.evidence_store import ReplayEvidenceRepository

TOOL_VERSION = "1.0.0"
RULE_VERSION = "evidence-v1"
DEFAULT_REPLAY_ROOT = Path(__file__).resolve().parents[3] / "data" / "replay"


def _meta(name: str, context: RuntimeContext, snapshot_id: str | None = None) -> ToolMeta:
    return ToolMeta(
        tool_name=name,
        tool_version=TOOL_VERSION,
        rule_version=RULE_VERSION,
        snapshot_id=snapshot_id or context.snapshot_id,
        trace_id=context.trace_id,
    )


class GetVisibleSnapshotTool:
    name = "get_visible_snapshot"
    version = TOOL_VERSION

    def __init__(self, repository: ReplayEvidenceRepository | None = None) -> None:
        self.repository = repository or ReplayEvidenceRepository(DEFAULT_REPLAY_ROOT)

    def invoke(self, context: RuntimeContext, arguments: dict[str, Any]) -> ToolResponse[dict[str, Any]]:
        try:
            stock_code = str(arguments["stock_code"])
            as_of = context.as_of.date().isoformat()
            snapshot_id = f"{stock_code}-{as_of}"
            if context.snapshot_id and context.snapshot_id != snapshot_id:
                raise ValueError("snapshot_id does not match stock_code and as_of")
            snapshot = self.repository.visible_snapshot(stock_code, as_of)
        except (KeyError, OSError, TypeError, ValueError) as exc:
            return ToolResponse(
                success=False,
                data=None,
                meta=_meta(self.name, context),
                error=ErrorDetail(code="evidence_unavailable", message=str(exc)),
            )
        return ToolResponse(success=True, data=snapshot, meta=_meta(self.name, context, snapshot_id))


class VerifyEvidenceTool:
    name = "verify_evidence"
    version = TOOL_VERSION

    def __init__(self, repository: ReplayEvidenceRepository | None = None) -> None:
        self.repository = repository or ReplayEvidenceRepository(DEFAULT_REPLAY_ROOT)

    def invoke(self, context: RuntimeContext, arguments: dict[str, Any]) -> ToolResponse[dict[str, Any]]:
        try:
            stock_code = str(arguments["stock_code"])
            result = self.repository.verify(stock_code)
        except (KeyError, OSError, TypeError, ValueError) as exc:
            return ToolResponse(
                success=False,
                data=None,
                meta=_meta(self.name, context),
                error=ErrorDetail(code="evidence_unavailable", message=str(exc)),
            )
        if not result["valid"]:
            return ToolResponse(
                success=False,
                data=result,
                meta=_meta(self.name, context),
                error=ErrorDetail(code="evidence_integrity_failed", message="one or more evidence files failed SHA-256 verification"),
            )
        return ToolResponse(success=True, data=result, meta=_meta(self.name, context))

