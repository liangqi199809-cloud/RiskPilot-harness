"""Production composition root for the current local Harness runtime."""

from __future__ import annotations

from pathlib import Path

from riskpilot.harness.orchestrator import HarnessOrchestrator
from riskpilot.harness.registry import ToolRegistry
from riskpilot.infrastructure.audit_store import SQLiteAuditRecorder
from riskpilot.infrastructure.evidence_store import ReplayEvidenceRepository
from riskpilot.infrastructure.leaderboard_store import SQLiteLeaderboardRepository
from riskpilot.infrastructure.report_store import SQLiteRiskReportRepository
from riskpilot.infrastructure.replay_sessions import DEFAULT_DATABASE_PATH, SQLiteReplaySessionRepository
from riskpilot.policies.guards import ScenarioToolPolicy, SnapshotRequiredPolicy
from riskpilot.tools import (
    BuildRiskReportTool,
    CalculateRiskBudgetTool,
    DrawHistoryCaseTool,
    ExtractRiskInputsTool,
    GetLeaderboardTool,
    GetReplaySessionTool,
    GetRiskReportTool,
    ListRiskReportsTool,
    GetVisibleSnapshotTool,
    PreviewReplayPositionTool,
    SubmitReplayActionTool,
    SubmitReplayScoreTool,
    VerifyEvidenceTool,
    VerifyRiskReportIntegrityTool,
)
from riskpilot.tools.evidence import DEFAULT_REPLAY_ROOT


def build_default_orchestrator(
    database_path: Path = DEFAULT_DATABASE_PATH,
    replay_root: Path = DEFAULT_REPLAY_ROOT,
) -> HarnessOrchestrator:
    """Wire every current tool through shared persistence and policy guards."""

    sessions = SQLiteReplaySessionRepository(database_path)
    leaderboard = SQLiteLeaderboardRepository(database_path)
    reports = SQLiteRiskReportRepository(database_path)
    evidence = ReplayEvidenceRepository(replay_root)
    registry = ToolRegistry()
    for tool in (
        CalculateRiskBudgetTool(),
        BuildRiskReportTool(reports),
        GetRiskReportTool(reports),
        ListRiskReportsTool(reports),
        VerifyRiskReportIntegrityTool(reports),
        GetVisibleSnapshotTool(evidence),
        VerifyEvidenceTool(evidence),
        ExtractRiskInputsTool(evidence),
        DrawHistoryCaseTool(sessions),
        GetReplaySessionTool(sessions),
        PreviewReplayPositionTool(sessions),
        SubmitReplayActionTool(sessions),
        SubmitReplayScoreTool(sessions, leaderboard),
        GetLeaderboardTool(leaderboard),
    ):
        registry.register(tool)
    return HarnessOrchestrator(
        registry=registry,
        policies=(ScenarioToolPolicy(), SnapshotRequiredPolicy()),
        audit_recorder=SQLiteAuditRecorder(database_path),
    )

