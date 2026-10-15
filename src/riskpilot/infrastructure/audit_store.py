"""Privacy-conscious SQLite audit records for Harness tool calls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Protocol
from uuid import uuid4

from riskpilot.harness.context import RuntimeContext
from riskpilot.harness.responses import ToolResponse


@dataclass(frozen=True, slots=True)
class AuditRecord:
    audit_id: str
    trace_id: str
    user_id: str
    entrypoint: str
    scenario: str
    tool_name: str
    success: bool
    tool_version: str
    rule_version: str
    snapshot_id: str | None
    input_sha256: str
    output_sha256: str
    error_code: str | None
    duration_ms: float
    created_at: str


class AuditRecorder(Protocol):
    def record(
        self,
        context: RuntimeContext,
        tool_name: str,
        input_sha256: str,
        output_sha256: str,
        response: ToolResponse[Any],
        duration_ms: float,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class SQLiteAuditRecorder:
    database_path: Path

    def __post_init__(self) -> None:
        path = Path(self.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        object.__setattr__(self, "database_path", path)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tool_audit (
                    audit_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    entrypoint TEXT NOT NULL,
                    scenario TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    tool_version TEXT NOT NULL,
                    rule_version TEXT NOT NULL,
                    snapshot_id TEXT,
                    input_sha256 TEXT NOT NULL,
                    output_sha256 TEXT NOT NULL,
                    error_code TEXT,
                    duration_ms REAL NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS tool_audit_trace_idx
                    ON tool_audit(trace_id, created_at);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def record(
        self,
        context: RuntimeContext,
        tool_name: str,
        input_sha256: str,
        output_sha256: str,
        response: ToolResponse[Any],
        duration_ms: float,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tool_audit (
                    audit_id, trace_id, user_id, entrypoint, scenario, tool_name,
                    success, tool_version, rule_version, snapshot_id,
                    input_sha256, output_sha256, error_code, duration_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()), context.trace_id, context.user_id, context.entrypoint,
                    context.scenario.value, tool_name, int(response.success),
                    response.meta.tool_version, response.meta.rule_version,
                    response.meta.snapshot_id, input_sha256, output_sha256,
                    response.error.code if response.error else None,
                    round(duration_ms, 3), datetime.now(timezone.utc).isoformat(),
                ),
            )

    def list_for_trace(self, trace_id: str) -> tuple[AuditRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tool_audit WHERE trace_id = ? ORDER BY created_at, audit_id",
                (trace_id,),
            ).fetchall()
        return tuple(
            AuditRecord(
                audit_id=row["audit_id"], trace_id=row["trace_id"],
                user_id=row["user_id"], entrypoint=row["entrypoint"],
                scenario=row["scenario"], tool_name=row["tool_name"],
                success=bool(row["success"]), tool_version=row["tool_version"],
                rule_version=row["rule_version"], snapshot_id=row["snapshot_id"],
                input_sha256=row["input_sha256"], output_sha256=row["output_sha256"],
                error_code=row["error_code"], duration_ms=row["duration_ms"],
                created_at=row["created_at"],
            )
            for row in rows
        )

