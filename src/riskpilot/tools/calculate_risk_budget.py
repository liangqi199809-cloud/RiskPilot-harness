"""Harness tool for deterministic risk-budget calculation."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from riskpilot.domain.risk import RULE_VERSION, RiskBudgetInput, calculate_risk_budget
from riskpilot.harness.context import RuntimeContext
from riskpilot.harness.responses import ErrorDetail, ToolMeta, ToolResponse


class CalculateRiskBudgetTool:
    name = "calculate_risk_budget"
    version = "1.0.0"

    def invoke(
        self,
        context: RuntimeContext,
        arguments: dict[str, Any],
    ) -> ToolResponse[dict[str, Any]]:
        meta = ToolMeta(
            tool_name=self.name,
            tool_version=self.version,
            rule_version=RULE_VERSION,
            snapshot_id=context.snapshot_id,
            trace_id=context.trace_id,
        )
        try:
            request = RiskBudgetInput(**arguments)
            result = calculate_risk_budget(request)
        except (TypeError, ValueError) as exc:
            return ToolResponse(
                success=False,
                data=None,
                meta=meta,
                error=ErrorDetail(
                    code="invalid_input",
                    message=str(exc),
                    retryable=False,
                ),
            )

        return ToolResponse(
            success=True,
            data=asdict(result),
            meta=meta,
        )

