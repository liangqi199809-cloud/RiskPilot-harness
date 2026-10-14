"""Server-side replay session storage abstraction and in-memory implementation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Protocol

from riskpilot.domain.replay_state import ReplayExperiment


class ReplaySessionRepository(Protocol):
    def get(self, experiment_id: str) -> ReplayExperiment: ...
    def save(self, experiment: ReplayExperiment) -> None: ...


@dataclass(slots=True)
class InMemoryReplaySessionRepository:
    """Process-local V2 store; replace with the Phase 5 database adapter."""

    _experiments: dict[str, ReplayExperiment] = field(default_factory=dict)

    def get(self, experiment_id: str) -> ReplayExperiment:
        try:
            return deepcopy(self._experiments[experiment_id])
        except KeyError as exc:
            raise LookupError("experiment not found") from exc

    def save(self, experiment: ReplayExperiment) -> None:
        self._experiments[experiment.experiment_id] = deepcopy(experiment)


DEFAULT_REPLAY_SESSIONS = InMemoryReplaySessionRepository()

