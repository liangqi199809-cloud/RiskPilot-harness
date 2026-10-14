"""Create trusted risk-engine inputs from a time-bounded evidence snapshot."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from riskpilot.domain.market_features import extract_risk_input_features
from riskpilot.harness.context import RuntimeContext
from riskpilot.harness.responses import ErrorDetail, ToolMeta, ToolResponse
from riskpilot.infrastructure.evidence_store import ReplayEvidenceRepository

TOOL_VERSION = "1.0.0"
RULE_VERSION = "market-features-v1"
DEFAULT_REPLAY_ROOT = Path(__file__).resolve().parents[3] / "data" / "replay"


class ExtractRiskInputsTool:
    """Read verified visible prices and derive inputs without client calculations."""

    name = "extract_risk_inputs"
    version = TOOL_VERSION

    def __init__(self, repository: ReplayEvidenceRepository | None = None) -> None:
        self.repository = repository or ReplayEvidenceRepository(DEFAULT_REPLAY_ROOT)

    def invoke(
        self,
        context: RuntimeContext,
        arguments: dict[str, Any],
    ) -> ToolResponse[dict[str, Any]]:
        stock_code = str(arguments.get("stock_code", ""))
        snapshot_id = f"{stock_code}-{context.as_of.date().isoformat()}"
        meta = ToolMeta(
            tool_name=self.name,
            tool_version=self.version,
            rule_version=RULE_VERSION,
            snapshot_id=snapshot_id,
            trace_id=context.trace_id,
        )
        try:
            if context.snapshot_id and context.snapshot_id != snapshot_id:
                raise ValueError("snapshot_id does not match stock_code and as_of")
            snapshot = self.repository.visible_snapshot(
                stock_code, context.as_of.date().isoformat()
            )
            features = extract_risk_input_features(snapshot["prices"])
        except (KeyError, OSError, TypeError, ValueError) as exc:
            return ToolResponse(
                success=False,
                data=None,
                meta=meta,
                error=ErrorDetail(code="risk_inputs_unavailable", message=str(exc)),
            )

        data = {
            "stock_code": stock_code,
            "stock_name": snapshot["stock_name"],
            **asdict(features),
        }
        return ToolResponse(success=True, data=data, meta=meta)

