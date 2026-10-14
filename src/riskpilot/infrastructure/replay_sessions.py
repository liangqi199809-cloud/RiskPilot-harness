"""Server-side replay session persistence implementations."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import sqlite3
from typing import Protocol

from riskpilot.domain.replay_state import ReplayExperiment, ReplayState


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


@dataclass(frozen=True, slots=True)
class SQLiteReplaySessionRepository:
    """Durable local storage with the same interface as future cloud adapters."""

    database_path: Path

    def __post_init__(self) -> None:
        path = Path(self.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        object.__setattr__(self, "database_path", path)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS replay_experiments (
                    experiment_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    step INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS replay_owner_idx ON replay_experiments(owner_id, updated_at)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def _encode(experiment: ReplayExperiment) -> str:
        return json.dumps(
            {
                "experiment_id": experiment.experiment_id,
                "owner_id": experiment.owner_id,
                "stock_code": experiment.stock_code,
                "decision_mode": experiment.decision_mode,
                "capital": experiment.capital,
                "max_loss": experiment.max_loss,
                "faction": experiment.faction,
                "state": experiment.state.value,
                "actions": experiment.actions,
                "idempotency_keys": sorted(experiment.idempotency_keys),
                "latest_result": experiment.latest_result,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @staticmethod
    def _decode(payload: str) -> ReplayExperiment:
        values = json.loads(payload)
        return ReplayExperiment(
            experiment_id=values["experiment_id"],
            owner_id=values["owner_id"],
            stock_code=values["stock_code"],
            decision_mode=values["decision_mode"],
            capital=values["capital"],
            max_loss=values["max_loss"],
            faction=values.get("faction"),
            state=ReplayState(values["state"]),
            actions=tuple(values.get("actions", ())),
            idempotency_keys=frozenset(values.get("idempotency_keys", ())),
            latest_result=values.get("latest_result", {}),
        )

    def get(self, experiment_id: str) -> ReplayExperiment:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM replay_experiments WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        if row is None:
            raise LookupError("experiment not found")
        return self._decode(row[0])

    def save(self, experiment: ReplayExperiment) -> None:
        payload = self._encode(experiment)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO replay_experiments (
                    experiment_id, owner_id, state, step, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(experiment_id) DO UPDATE SET
                    owner_id = excluded.owner_id,
                    state = excluded.state,
                    step = excluded.step,
                    payload_json = excluded.payload_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    experiment.experiment_id,
                    experiment.owner_id,
                    experiment.state.value,
                    experiment.step,
                    payload,
                ),
            )

    def backup_to(self, destination: Path) -> Path:
        """Create a consistent SQLite backup without stopping the application."""

        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as source, sqlite3.connect(destination) as target:
            source.backup(target)
        return destination


DEFAULT_DATABASE_PATH = Path(
    os.environ.get(
        "RISKPILOT_DATABASE_PATH",
        Path(__file__).resolve().parents[3] / "data" / "runtime" / "riskpilot-v2.sqlite3",
    )
)
DEFAULT_REPLAY_SESSIONS = SQLiteReplaySessionRepository(DEFAULT_DATABASE_PATH)

