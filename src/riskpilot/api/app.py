"""FastAPI application that exposes only governed Harness operations."""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import asdict
import re
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from riskpilot.api.auth import (
    AuthenticatedIdentity,
    IdentityResolver,
    identity_resolver_from_environment,
)
from riskpilot.api.schemas import (
    DrawCaseRequest,
    HistoricalRequest,
    LeaderboardRequest,
    ReplayActionRequest,
    ReplayPreviewRequest,
    ReplaySessionRequest,
    ReportCreateRequest,
    ReportListRequest,
    ReportRequest,
    RiskBudgetRequest,
    StockRequest,
    SubmitScoreRequest,
)
from riskpilot.harness.context import ProductScenario, RuntimeContext
from riskpilot.harness.defaults import build_default_orchestrator
from riskpilot.harness.orchestrator import HarnessOrchestrator
from riskpilot.harness.responses import ToolResponse
from riskpilot.agents import (
    FundamentalInterpreter,
    ModelGateway,
    NewsInterpreter,
    OfflineModelGateway,
    PerspectiveEvidence,
    TechnicalInterpreter,
)

API_VERSION = "2.0.0-dev"


def _status_for(result: ToolResponse[Any]) -> int:
    if result.success:
        return 200
    code = result.error.code if result.error else ""
    if code in {"policy_denied", "forbidden"}:
        return 403
    if code == "tool_not_found":
        return 404
    if code in {"duplicate_score", "idempotency_conflict"}:
        return 409
    if code in {"tool_execution_failed", "leaderboard_unavailable"}:
        return 503
    return 400


def create_v2_app(
    orchestrator: HarnessOrchestrator | None = None,
    identity_resolver: IdentityResolver | None = None,
    model_gateway: ModelGateway | None = None,
) -> FastAPI:
    runtime = orchestrator or build_default_orchestrator()
    identities = identity_resolver if identity_resolver is not None else identity_resolver_from_environment()
    gateway = model_gateway or OfflineModelGateway()
    application = FastAPI(
        title="RiskPilot V2 Harness API",
        description="Historical financial-risk education API; no live trading or return promises.",
        version=API_VERSION,
    )

    def authenticate(authorization: str | None = Header(default=None)) -> AuthenticatedIdentity:
        if identities is None:
            raise HTTPException(status_code=503, detail={"code": "identity_not_configured", "message": "API identity service is not configured"})
        scheme, separator, token = (authorization or "").partition(" ")
        if not separator or scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "valid bearer token required"})
        if len(token.strip()) > 512:
            raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "valid bearer token required"})
        identity = identities.resolve(token.strip())
        if identity is None:
            raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "valid bearer token required"})
        return identity

    def context_for(
        request: HistoricalRequest,
        identity: AuthenticatedIdentity,
        arguments: dict[str, Any],
        trace_id: str | None,
    ) -> RuntimeContext:
        if trace_id is not None and (
            len(trace_id.strip()) > 128
            or (trace_id.strip() and re.fullmatch(r"[A-Za-z0-9._:-]+", trace_id.strip()) is None)
        ):
            raise HTTPException(status_code=422, detail={"code": "invalid_context", "message": "X-Trace-ID format is invalid"})
        try:
            return RuntimeContext(
                user_id=identity.user_id,
                entrypoint="v2_http_api",
                scenario=ProductScenario.CONSUMER_EDUCATION,
                as_of=request.as_of,
                trace_id=trace_id.strip() if trace_id and trace_id.strip() else str(uuid4()),
                experiment_id=str(arguments.get("experiment_id")) if arguments.get("experiment_id") else None,
                snapshot_id=request.snapshot_id,
                permissions=identity.permissions,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "invalid_context", "message": str(exc)}) from exc

    def respond(result: ToolResponse[Any], context: RuntimeContext) -> JSONResponse:
        return JSONResponse(
            status_code=_status_for(result), content=result.to_dict(),
            headers={"X-Trace-ID": context.trace_id},
        )

    def call(
        tool_name: str, request: HistoricalRequest, identity: AuthenticatedIdentity,
        arguments: dict[str, Any], trace_id: str | None,
    ) -> JSONResponse:
        context = context_for(request, identity, arguments, trace_id)
        result = runtime.invoke(tool_name, context, arguments)
        return respond(result, context)

    @application.get("/api/v2/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "RiskPilot V2 Harness API",
            "version": API_VERSION,
            "identity_configured": identities is not None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @application.post("/api/v2/evidence/verify")
    def verify_evidence(request: StockRequest, identity: AuthenticatedIdentity = Depends(authenticate), x_trace_id: str | None = Header(default=None)):
        return call("verify_evidence", request, identity, {"stock_code": request.stock_code}, x_trace_id)

    @application.post("/api/v2/evidence/snapshot")
    def visible_snapshot(request: StockRequest, identity: AuthenticatedIdentity = Depends(authenticate), x_trace_id: str | None = Header(default=None)):
        return call("get_visible_snapshot", request, identity, {"stock_code": request.stock_code}, x_trace_id)

    @application.post("/api/v2/risk/inputs")
    def risk_inputs(request: StockRequest, identity: AuthenticatedIdentity = Depends(authenticate), x_trace_id: str | None = Header(default=None)):
        return call("extract_risk_inputs", request, identity, {"stock_code": request.stock_code}, x_trace_id)

    @application.post("/api/v2/risk/budget")
    def risk_budget(request: RiskBudgetRequest, identity: AuthenticatedIdentity = Depends(authenticate), x_trace_id: str | None = Header(default=None)):
        arguments = request.model_dump(exclude={"as_of", "snapshot_id"})
        return call("calculate_risk_budget", request, identity, arguments, x_trace_id)

    @application.post("/api/v2/replay/cases")
    def draw_case(request: DrawCaseRequest, identity: AuthenticatedIdentity = Depends(authenticate), x_trace_id: str | None = Header(default=None)):
        arguments = request.model_dump(exclude={"as_of", "snapshot_id"}, exclude_none=True)
        return call("draw_history_case", request, identity, arguments, x_trace_id)

    @application.post("/api/v2/replay/preview")
    def preview(request: ReplayPreviewRequest, identity: AuthenticatedIdentity = Depends(authenticate), x_trace_id: str | None = Header(default=None)):
        arguments = request.model_dump(exclude={"as_of", "snapshot_id"})
        return call("preview_replay_position", request, identity, arguments, x_trace_id)

    @application.post("/api/v2/replay/session")
    def replay_session(request: ReplaySessionRequest, identity: AuthenticatedIdentity = Depends(authenticate), x_trace_id: str | None = Header(default=None)):
        return call("get_replay_session", request, identity, {"experiment_id": request.experiment_id}, x_trace_id)

    @application.post("/api/v2/replay/actions")
    def submit_action(request: ReplayActionRequest, identity: AuthenticatedIdentity = Depends(authenticate), x_trace_id: str | None = Header(default=None)):
        arguments = request.model_dump(exclude={"as_of", "snapshot_id"})
        return call("submit_replay_action", request, identity, arguments, x_trace_id)

    @application.post("/api/v2/replay/scores")
    def submit_score(request: SubmitScoreRequest, identity: AuthenticatedIdentity = Depends(authenticate), x_trace_id: str | None = Header(default=None)):
        arguments = request.model_dump(exclude={"as_of", "snapshot_id"})
        return call("submit_replay_score", request, identity, arguments, x_trace_id)

    @application.post("/api/v2/leaderboard/query")
    def leaderboard(request: LeaderboardRequest, identity: AuthenticatedIdentity = Depends(authenticate), x_trace_id: str | None = Header(default=None)):
        return call("get_leaderboard", request, identity, {"limit": request.limit}, x_trace_id)

    @application.post("/api/v2/reports")
    def create_report(request: ReportCreateRequest, identity: AuthenticatedIdentity = Depends(authenticate), x_trace_id: str | None = Header(default=None)):
        context = context_for(request, identity, {}, x_trace_id)
        risk_inputs = runtime.invoke("extract_risk_inputs", context, {"stock_code": request.stock_code})
        if not risk_inputs.success:
            return respond(risk_inputs, context)
        snapshot = runtime.invoke("get_visible_snapshot", context, {"stock_code": request.stock_code})
        if not snapshot.success:
            return respond(snapshot, context)
        values = risk_inputs.data
        risk_budget = runtime.invoke("calculate_risk_budget", context, {
            "stock_code": request.stock_code, "stock_name": values["stock_name"],
            "capital": request.capital, "max_loss": request.max_loss,
            "current_price": values["current_price"], "atr_14": values["atr_14"],
            "key_support": values["key_support"], "board": "main",
        })
        if not risk_budget.success:
            return respond(risk_budget, context)

        technical_evidence = PerspectiveEvidence(
            evidence_id=f"{request.snapshot_id}:technical", evidence_type="technical_indicators",
            source=snapshot.data["source"], as_of=request.as_of.isoformat(), facts=values,
        )
        technical = TechnicalInterpreter(gateway).interpret((technical_evidence,))
        fundamental = FundamentalInterpreter(gateway).interpret(())
        news_evidence = tuple(
            PerspectiveEvidence(
                evidence_id=f"{request.snapshot_id}:document:{index}",
                evidence_type="official_document", source=str(item.get("source") or snapshot.data["source"]),
                as_of=str(item.get("published_date") or request.as_of.date().isoformat()), facts=item,
            )
            for index, item in enumerate(snapshot.data.get("documents", ()), start=1)
            if item
        )
        news = NewsInterpreter(gateway).interpret(news_evidence)
        position = risk_budget.data["position"]
        arguments = {
            "idempotency_key": request.idempotency_key,
            "stock_code": request.stock_code, "stock_name": values["stock_name"],
            "capital": request.capital, "max_loss": request.max_loss,
            "current_price": values["current_price"],
            "stop_price": position["stop_loss_price"], "shares": position["final_shares"],
            "standard_loss": position["standard_loss"],
            "price_rows": snapshot.data["prices"],
            "perspectives": {
                "technical": asdict(technical), "fundamental": asdict(fundamental),
                "news": asdict(news),
            },
            "evidence": {
                "source": snapshot.data["source"],
                "license_status": snapshot.data["license_status"],
                "file_hashes": snapshot.data["file_hashes"],
                "documents": snapshot.data.get("documents", ()),
                "chart_data": snapshot.data["prices"],
            },
        }
        return respond(runtime.invoke("build_risk_report", context, arguments), context)

    @application.post("/api/v2/reports/query")
    def get_report(request: ReportRequest, identity: AuthenticatedIdentity = Depends(authenticate), x_trace_id: str | None = Header(default=None)):
        return call("get_risk_report", request, identity, {"report_id": request.report_id}, x_trace_id)

    @application.post("/api/v2/reports/integrity")
    def verify_report(request: ReportRequest, identity: AuthenticatedIdentity = Depends(authenticate), x_trace_id: str | None = Header(default=None)):
        return call("verify_report_integrity", request, identity, {"report_id": request.report_id}, x_trace_id)

    @application.post("/api/v2/reports/list")
    def list_reports(request: ReportListRequest, identity: AuthenticatedIdentity = Depends(authenticate), x_trace_id: str | None = Header(default=None)):
        return call("list_risk_reports", request, identity, {"limit": request.limit}, x_trace_id)

    return application


app = create_v2_app()
