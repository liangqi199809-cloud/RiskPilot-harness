"""FastAPI application that exposes only governed Harness operations."""

from __future__ import annotations

from datetime import datetime, timezone
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
    RiskBudgetRequest,
    StockRequest,
    SubmitScoreRequest,
)
from riskpilot.harness.context import ProductScenario, RuntimeContext
from riskpilot.harness.defaults import build_default_orchestrator
from riskpilot.harness.orchestrator import HarnessOrchestrator
from riskpilot.harness.responses import ToolResponse

API_VERSION = "2.0.0-dev"


def _status_for(result: ToolResponse[Any]) -> int:
    if result.success:
        return 200
    code = result.error.code if result.error else ""
    if code in {"policy_denied", "forbidden"}:
        return 403
    if code == "tool_not_found":
        return 404
    if code in {"duplicate_score"}:
        return 409
    if code in {"tool_execution_failed", "leaderboard_unavailable"}:
        return 503
    return 400


def create_v2_app(
    orchestrator: HarnessOrchestrator | None = None,
    identity_resolver: IdentityResolver | None = None,
) -> FastAPI:
    runtime = orchestrator or build_default_orchestrator()
    identities = identity_resolver if identity_resolver is not None else identity_resolver_from_environment()
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

    def call(
        tool_name: str,
        request: HistoricalRequest,
        identity: AuthenticatedIdentity,
        arguments: dict[str, Any],
        trace_id: str | None,
    ) -> JSONResponse:
        if trace_id is not None and (
            len(trace_id.strip()) > 128
            or (trace_id.strip() and re.fullmatch(r"[A-Za-z0-9._:-]+", trace_id.strip()) is None)
        ):
            raise HTTPException(status_code=422, detail={"code": "invalid_context", "message": "X-Trace-ID format is invalid"})
        try:
            context = RuntimeContext(
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
        result = runtime.invoke(tool_name, context, arguments)
        return JSONResponse(
            status_code=_status_for(result),
            content=result.to_dict(),
            headers={"X-Trace-ID": context.trace_id},
        )

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

    return application


app = create_v2_app()
