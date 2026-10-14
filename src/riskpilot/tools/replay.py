"""Stateful Harness tools for the historical replay challenge."""

from __future__ import annotations

from copy import deepcopy
import secrets
from typing import Any
from uuid import uuid4

from backend.replay import Action, ReplayRequest, STOCKS, replay
from riskpilot.domain.replay_state import (
    ReplayExperiment,
    ReplayState,
    ReplayTransitionError,
)
from riskpilot.harness.context import RuntimeContext
from riskpilot.harness.responses import ErrorDetail, ToolMeta, ToolResponse
from riskpilot.infrastructure.replay_sessions import (
    DEFAULT_REPLAY_SESSIONS,
    ReplaySessionRepository,
)

TOOL_VERSION = "1.0.0"
RULE_VERSION = "replay-v4"


def _meta(name: str, context: RuntimeContext, experiment: ReplayExperiment | None = None) -> ToolMeta:
    snapshot_id = context.snapshot_id
    if experiment and experiment.latest_result:
        snapshot_id = f"{experiment.stock_code}-{experiment.latest_result['cutoff']}"
    return ToolMeta(
        tool_name=name,
        tool_version=TOOL_VERSION,
        rule_version=RULE_VERSION,
        snapshot_id=snapshot_id,
        trace_id=context.trace_id,
    )


def _result_for(experiment: ReplayExperiment, preview: dict[str, Any] | None = None) -> dict[str, Any]:
    result = experiment.latest_result
    payload = {
        "experiment_id": experiment.experiment_id,
        "state": experiment.state.value,
        "step": experiment.step,
        "total_decisions": experiment.total_decisions,
        "stock_code": experiment.stock_code,
        "decision_mode": experiment.decision_mode,
        "cutoff": result.get("cutoff"),
        "account": deepcopy(result.get("account")),
        "finished": experiment.state is ReplayState.FINISHED,
    }
    if preview is not None:
        payload["preview"] = preview
    return payload


def _run(experiment: ReplayExperiment, actions: tuple[float | None, ...], preview_target: float | None = None) -> dict[str, Any]:
    return replay(
        ReplayRequest(
            stock_code=experiment.stock_code,
            decision_mode=experiment.decision_mode,
            capital=experiment.capital,
            max_loss=experiment.max_loss,
            faction=experiment.faction,
            actions=[Action(target_value=value) for value in actions],
            preview_target=preview_target,
        )
    )


class DrawHistoryCaseTool:
    """Select a case and create a server-owned experiment."""

    name = "draw_history_case"
    version = TOOL_VERSION

    def __init__(self, sessions: ReplaySessionRepository = DEFAULT_REPLAY_SESSIONS) -> None:
        self.sessions = sessions

    def invoke(self, context: RuntimeContext, arguments: dict[str, Any]) -> ToolResponse[dict[str, Any]]:
        try:
            candidates = list(STOCKS)
            industry = arguments.get("industry")
            if industry:
                candidates = [code for code in candidates if STOCKS[code]["industry"] == industry]
            requested_code = arguments.get("stock_code")
            if requested_code is not None:
                if requested_code not in candidates:
                    raise ValueError("requested stock is not an available case")
                stock_code = requested_code
            else:
                if not candidates:
                    raise ValueError("no historical cases match the requested filter")
                stock_code = secrets.choice(candidates)
            experiment = ReplayExperiment(
                experiment_id=str(uuid4()),
                owner_id=context.user_id,
                stock_code=stock_code,
                decision_mode=str(arguments.get("decision_mode", "monthly")),
                capital=float(arguments.get("capital", 100000)),
                max_loss=float(arguments.get("max_loss", 2000)),
                faction=arguments.get("faction"),
                state=ReplayState.DECISION_PENDING,
            )
            initial = _run(experiment, ())
            experiment = ReplayExperiment(
                experiment_id=experiment.experiment_id,
                owner_id=experiment.owner_id,
                stock_code=experiment.stock_code,
                decision_mode=experiment.decision_mode,
                capital=experiment.capital,
                max_loss=experiment.max_loss,
                faction=experiment.faction,
                state=ReplayState.DECISION_PENDING,
                latest_result=initial,
            )
            self.sessions.save(experiment)
        except (KeyError, OSError, TypeError, ValueError) as exc:
            return ToolResponse(
                success=False,
                data=None,
                meta=_meta(self.name, context),
                error=ErrorDetail(code="case_creation_failed", message=str(exc)),
            )
        return ToolResponse(success=True, data=_result_for(experiment), meta=_meta(self.name, context, experiment))


class PreviewReplayPositionTool:
    """Preview a target position without changing the saved experiment."""

    name = "preview_replay_position"
    version = TOOL_VERSION

    def __init__(self, sessions: ReplaySessionRepository = DEFAULT_REPLAY_SESSIONS) -> None:
        self.sessions = sessions

    def invoke(self, context: RuntimeContext, arguments: dict[str, Any]) -> ToolResponse[dict[str, Any]]:
        experiment = None
        try:
            experiment = self.sessions.get(str(arguments["experiment_id"]))
            experiment.assert_owner(context.user_id)
            if experiment.state is ReplayState.FINISHED:
                raise ReplayTransitionError("finished experiment cannot be previewed")
            expected_step = int(arguments["expected_step"])
            if expected_step != experiment.step:
                raise ReplayTransitionError(f"expected_step must equal current step {experiment.step}")
            preview = _run(experiment, experiment.actions, float(arguments["target_value"]))
            preview_data = {
                "target_value": float(arguments["target_value"]),
                "preview_shares": preview["preview_shares"],
                "scenarios": preview["scenarios"],
            }
        except PermissionError as exc:
            return ToolResponse(success=False, data=None, meta=_meta(self.name, context, experiment), error=ErrorDetail(code="forbidden", message=str(exc)))
        except (KeyError, LookupError, OSError, TypeError, ValueError) as exc:
            return ToolResponse(success=False, data=None, meta=_meta(self.name, context, experiment), error=ErrorDetail(code="invalid_replay_transition", message=str(exc)))
        return ToolResponse(success=True, data=_result_for(experiment, preview_data), meta=_meta(self.name, context, experiment))


class SubmitReplayActionTool:
    """Accept exactly one action for the current step and advance server state."""

    name = "submit_replay_action"
    version = TOOL_VERSION

    def __init__(self, sessions: ReplaySessionRepository = DEFAULT_REPLAY_SESSIONS) -> None:
        self.sessions = sessions

    def invoke(self, context: RuntimeContext, arguments: dict[str, Any]) -> ToolResponse[dict[str, Any]]:
        experiment = None
        try:
            experiment = self.sessions.get(str(arguments["experiment_id"]))
            experiment.assert_owner(context.user_id)
            target = arguments.get("target_value")
            target = None if target is None else float(target)
            expected_step = int(arguments["expected_step"])
            key = str(arguments["idempotency_key"])
            # Validate transition before doing the potentially heavier replay.
            if experiment.state is ReplayState.FINISHED:
                raise ReplayTransitionError("finished experiment cannot be modified")
            if expected_step != experiment.step:
                raise ReplayTransitionError(f"expected_step must equal current step {experiment.step}")
            if not key.strip() or key in experiment.idempotency_keys:
                raise ReplayTransitionError("duplicate or empty idempotency_key")
            actions = (*experiment.actions, target)
            result = _run(experiment, actions)
            experiment = experiment.submit(target, expected_step, key, result)
            self.sessions.save(experiment)
        except PermissionError as exc:
            return ToolResponse(success=False, data=None, meta=_meta(self.name, context, experiment), error=ErrorDetail(code="forbidden", message=str(exc)))
        except (KeyError, LookupError, OSError, TypeError, ValueError) as exc:
            return ToolResponse(success=False, data=None, meta=_meta(self.name, context, experiment), error=ErrorDetail(code="invalid_replay_transition", message=str(exc)))
        return ToolResponse(success=True, data=_result_for(experiment), meta=_meta(self.name, context, experiment))

