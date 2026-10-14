"""Server-owned replay experiment state and legal transitions."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any


class ReplayState(StrEnum):
    DECISION_PENDING = "decision_pending"
    FINISHED = "finished"


class ReplayTransitionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ReplayExperiment:
    experiment_id: str
    owner_id: str
    stock_code: str
    decision_mode: str
    capital: float
    max_loss: float
    faction: str | None
    state: ReplayState
    actions: tuple[float | None, ...] = ()
    idempotency_keys: frozenset[str] = field(default_factory=frozenset)
    latest_result: dict[str, Any] = field(default_factory=dict)

    @property
    def step(self) -> int:
        return len(self.actions)

    @property
    def total_decisions(self) -> int:
        return int(self.latest_result.get("total_decisions", 0))

    def assert_owner(self, user_id: str) -> None:
        if self.owner_id != user_id:
            raise PermissionError("experiment belongs to another user")

    def submit(
        self,
        target_value: float | None,
        expected_step: int,
        idempotency_key: str,
        result: dict[str, Any],
    ) -> "ReplayExperiment":
        if self.state is ReplayState.FINISHED:
            raise ReplayTransitionError("finished experiment cannot be modified")
        if expected_step != self.step:
            raise ReplayTransitionError(
                f"expected_step must equal current step {self.step}"
            )
        if not idempotency_key.strip():
            raise ReplayTransitionError("idempotency_key must not be empty")
        if idempotency_key in self.idempotency_keys:
            raise ReplayTransitionError("duplicate submission")
        new_actions = (*self.actions, target_value)
        state = ReplayState.FINISHED if result.get("finished") else ReplayState.DECISION_PENDING
        return replace(
            self,
            actions=new_actions,
            idempotency_keys=self.idempotency_keys | {idempotency_key},
            latest_result=result,
            state=state,
        )

