"""Harness tools for verified score submission and leaderboard reads."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any
from uuid import uuid4

from backend.replay import Action, ReplayRequest, replay
from riskpilot.domain.replay_state import ReplayState
from riskpilot.domain.scoring import ReplayScore, normalize_profile
from riskpilot.harness.context import RuntimeContext
from riskpilot.harness.responses import ErrorDetail, ToolMeta, ToolResponse
from riskpilot.infrastructure.leaderboard_store import DuplicateScoreError, SQLiteLeaderboardRepository
from riskpilot.infrastructure.replay_sessions import DEFAULT_DATABASE_PATH, DEFAULT_REPLAY_SESSIONS, ReplaySessionRepository

TOOL_VERSION = "1.0.0"
RULE_VERSION = "score-v1"
DEFAULT_LEADERBOARD = SQLiteLeaderboardRepository(DEFAULT_DATABASE_PATH)


def _meta(name: str, context: RuntimeContext, snapshot_id: str | None = None) -> ToolMeta:
    return ToolMeta(tool_name=name, tool_version=TOOL_VERSION, rule_version=RULE_VERSION,
                    snapshot_id=snapshot_id, trace_id=context.trace_id)


class SubmitReplayScoreTool:
    """Re-run a completed server experiment and persist one verified score."""

    name = "submit_replay_score"
    version = TOOL_VERSION

    def __init__(self, sessions: ReplaySessionRepository = DEFAULT_REPLAY_SESSIONS,
                 leaderboard: SQLiteLeaderboardRepository = DEFAULT_LEADERBOARD) -> None:
        self.sessions = sessions
        self.leaderboard = leaderboard

    def invoke(self, context: RuntimeContext, arguments: dict[str, Any]) -> ToolResponse[dict[str, Any]]:
        experiment = None
        try:
            experiment = self.sessions.get(str(arguments["experiment_id"]))
            experiment.assert_owner(context.user_id)
            if experiment.state is not ReplayState.FINISHED:
                raise ValueError("only a finished experiment can submit a score")
            faction = experiment.faction or str(arguments.get("faction", "jin"))
            profile = normalize_profile(context.user_id, str(arguments["display_name"]),
                                        str(arguments.get("avatar", "🎮")), faction)
            verified = replay(ReplayRequest(
                stock_code=experiment.stock_code,
                decision_mode=experiment.decision_mode,
                capital=experiment.capital,
                max_loss=experiment.max_loss,
                faction=experiment.faction,
                actions=[Action(target_value=value) for value in experiment.actions],
            ))
            if not verified["finished"]:
                raise ValueError("server replay did not reach a finished state")
            if verified["account"] != experiment.latest_result.get("account"):
                raise ValueError("saved experiment does not match server replay")
            pnl = float(verified["account"]["pnl"])
            score = ReplayScore(
                score_id=str(uuid4()), experiment_id=experiment.experiment_id,
                user_id=context.user_id, stock_code=experiment.stock_code,
                stock_name=verified["name"], decision_mode=experiment.decision_mode,
                capital=experiment.capital, pnl=pnl,
                pnl_pct=round(pnl / experiment.capital * 100, 2), faction=profile.faction,
            )
            self.leaderboard.save_verified_score(profile, score)
            board = self.leaderboard.leaderboard(limit=100)
            rank = next((item["rank"] for item in board["players"]
                         if item["user_id"] == context.user_id), None)
        except PermissionError as exc:
            return ToolResponse(success=False, data=None, meta=_meta(self.name, context),
                                error=ErrorDetail(code="forbidden", message=str(exc)))
        except DuplicateScoreError as exc:
            return ToolResponse(success=False, data=None, meta=_meta(self.name, context),
                                error=ErrorDetail(code="duplicate_score", message=str(exc)))
        except (KeyError, LookupError, OSError, TypeError, ValueError) as exc:
            return ToolResponse(success=False, data=None, meta=_meta(self.name, context),
                                error=ErrorDetail(code="score_rejected", message=str(exc)))
        snapshot_id = f"{experiment.stock_code}-{verified['cutoff']}"
        return ToolResponse(success=True, data={"score": asdict(score), "rank": rank},
                            meta=_meta(self.name, context, snapshot_id))


class GetLeaderboardTool:
    name = "get_leaderboard"
    version = TOOL_VERSION

    def __init__(self, leaderboard: SQLiteLeaderboardRepository = DEFAULT_LEADERBOARD) -> None:
        self.leaderboard = leaderboard

    def invoke(self, context: RuntimeContext, arguments: dict[str, Any]) -> ToolResponse[dict[str, Any]]:
        try:
            result = self.leaderboard.leaderboard(int(arguments.get("limit", 20)))
        except (OSError, TypeError, ValueError) as exc:
            return ToolResponse(success=False, data=None, meta=_meta(self.name, context),
                                error=ErrorDetail(code="leaderboard_unavailable", message=str(exc), retryable=True))
        return ToolResponse(success=True, data=result, meta=_meta(self.name, context))

