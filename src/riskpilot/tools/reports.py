"""Harness tools for V2 risk-report generation, retrieval, and integrity."""

from __future__ import annotations

from dataclasses import fields
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from riskpilot.agents.report_perspectives import PerspectiveResult
from riskpilot.domain.reporting import REPORT_RULE_VERSION, build_deterministic_report_core
from riskpilot.domain.risk_report import RISK_REPORT_RULE_VERSION, build_risk_report, sha256_value, verify_risk_report
from riskpilot.harness.context import RuntimeContext
from riskpilot.harness.responses import ErrorDetail, ToolMeta, ToolResponse
from riskpilot.infrastructure.report_store import DuplicateReportRequestError, SQLiteRiskReportRepository, StoredRiskReport
from riskpilot.infrastructure.replay_sessions import DEFAULT_DATABASE_PATH


TOOL_VERSION = "1.0.0"
_PERSPECTIVE_FIELDS = {item.name for item in fields(PerspectiveResult)}


def _meta(name: str, context: RuntimeContext) -> ToolMeta:
    return ToolMeta(name, TOOL_VERSION, RISK_REPORT_RULE_VERSION, context.trace_id, context.snapshot_id)


def _perspectives(arguments: dict[str, Any]) -> dict[str, PerspectiveResult]:
    raw = arguments.get("perspectives")
    if not isinstance(raw, dict):
        raise ValueError("perspectives must be an object")
    result = {}
    for name in ("technical", "fundamental", "news"):
        value = raw.get(name)
        if not isinstance(value, dict) or set(value) - _PERSPECTIVE_FIELDS:
            raise ValueError(f"invalid {name} perspective structure")
        result[name] = PerspectiveResult(**value)
    return result


class BuildRiskReportTool:
    name = "build_risk_report"
    version = TOOL_VERSION

    def __init__(self, reports: SQLiteRiskReportRepository | None = None) -> None:
        self.reports = reports or SQLiteRiskReportRepository(DEFAULT_DATABASE_PATH)

    def invoke(self, context: RuntimeContext, arguments: dict[str, Any]) -> ToolResponse[dict[str, Any]]:
        try:
            if not context.snapshot_id:
                raise ValueError("snapshot_id is required")
            key = str(arguments["idempotency_key"])
            if not key.strip() or len(key) > 128:
                raise ValueError("idempotency_key must contain 1-128 characters")
            rows = arguments["price_rows"]
            core = build_deterministic_report_core(
                rows, capital=float(arguments["capital"]), max_loss=float(arguments["max_loss"]),
                current_price=float(arguments["current_price"]), stop_price=float(arguments["stop_price"]),
                shares=int(arguments["shares"]), standard_loss=float(arguments["standard_loss"]),
            )
            perspective_values = _perspectives(arguments)
            request_hash = sha256_value({
                "owner_id": context.user_id, "snapshot_id": context.snapshot_id,
                "as_of": context.as_of.isoformat(),
                "idempotency_key": key,
                "stock_code": arguments["stock_code"],
                "stock_name": arguments["stock_name"],
                "capital": arguments["capital"], "max_loss": arguments["max_loss"],
                "current_price": arguments["current_price"],
                "stop_price": arguments["stop_price"], "shares": arguments["shares"],
                "standard_loss": arguments["standard_loss"],
                "price_rows": arguments["price_rows"],
                "report_rule_version": RISK_REPORT_RULE_VERSION,
                "domain_rule_version": REPORT_RULE_VERSION,
            })
            built = build_risk_report(
                report_id=str(uuid5(NAMESPACE_URL, request_hash)), owner_id=context.user_id,
                snapshot_id=context.snapshot_id, as_of=context.as_of.isoformat(),
                stock_code=str(arguments["stock_code"]), stock_name=str(arguments["stock_name"]),
                capital=float(arguments["capital"]), max_loss=float(arguments["max_loss"]),
                core=core, perspectives=perspective_values,
                evidence=dict(arguments.get("evidence", {})),
            )
            stored, created = self.reports.save(StoredRiskReport(
                report_id=built.payload["report_id"], owner_id=context.user_id,
                snapshot_id=context.snapshot_id, idempotency_key=key,
                request_hash=request_hash, payload=built.payload, markdown=built.markdown,
            ))
        except DuplicateReportRequestError as exc:
            return ToolResponse(False, None, _meta(self.name, context), error=ErrorDetail("idempotency_conflict", str(exc)))
        except (KeyError, TypeError, ValueError, OSError) as exc:
            return ToolResponse(False, None, _meta(self.name, context), error=ErrorDetail("report_build_failed", str(exc)))
        return ToolResponse(True, {"report": stored.payload, "markdown": stored.markdown, "created": created}, _meta(self.name, context))


class GetRiskReportTool:
    name = "get_risk_report"
    version = TOOL_VERSION

    def __init__(self, reports: SQLiteRiskReportRepository | None = None) -> None:
        self.reports = reports or SQLiteRiskReportRepository(DEFAULT_DATABASE_PATH)

    def invoke(self, context: RuntimeContext, arguments: dict[str, Any]) -> ToolResponse[dict[str, Any]]:
        try:
            report = self.reports.get(str(arguments["report_id"]))
            report.assert_owner(context.user_id)
        except PermissionError as exc:
            return ToolResponse(False, None, _meta(self.name, context), error=ErrorDetail("forbidden", str(exc)))
        except (KeyError, LookupError, TypeError, ValueError, OSError) as exc:
            return ToolResponse(False, None, _meta(self.name, context), error=ErrorDetail("report_unavailable", str(exc)))
        return ToolResponse(True, {"report": report.payload, "markdown": report.markdown}, _meta(self.name, context))


class VerifyRiskReportIntegrityTool:
    name = "verify_report_integrity"
    version = TOOL_VERSION

    def __init__(self, reports: SQLiteRiskReportRepository | None = None) -> None:
        self.reports = reports or SQLiteRiskReportRepository(DEFAULT_DATABASE_PATH)

    def invoke(self, context: RuntimeContext, arguments: dict[str, Any]) -> ToolResponse[dict[str, Any]]:
        try:
            report = self.reports.get(str(arguments["report_id"]))
            report.assert_owner(context.user_id)
            result = {"report_id": report.report_id, **verify_risk_report(report.payload, report.markdown)}
        except PermissionError as exc:
            return ToolResponse(False, None, _meta(self.name, context), error=ErrorDetail("forbidden", str(exc)))
        except (KeyError, LookupError, TypeError, ValueError, OSError) as exc:
            return ToolResponse(False, None, _meta(self.name, context), error=ErrorDetail("report_unavailable", str(exc)))
        return ToolResponse(True, result, _meta(self.name, context))


class ListRiskReportsTool:
    name = "list_risk_reports"
    version = TOOL_VERSION

    def __init__(self, reports: SQLiteRiskReportRepository | None = None) -> None:
        self.reports = reports or SQLiteRiskReportRepository(DEFAULT_DATABASE_PATH)

    def invoke(self, context: RuntimeContext, arguments: dict[str, Any]) -> ToolResponse[dict[str, Any]]:
        try:
            limit = int(arguments.get("limit", 20))
            reports = self.reports.list_for_owner(context.user_id, limit)
        except (OSError, TypeError, ValueError) as exc:
            return ToolResponse(False, None, _meta(self.name, context), error=ErrorDetail("report_unavailable", str(exc)))
        return ToolResponse(True, {"reports": reports, "count": len(reports)}, _meta(self.name, context))

