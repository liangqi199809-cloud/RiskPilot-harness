"""SQLite persistence for complete V2 risk reports."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from typing import Any


class DuplicateReportRequestError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StoredRiskReport:
    report_id: str
    owner_id: str
    snapshot_id: str
    idempotency_key: str
    request_hash: str
    payload: dict[str, Any]
    markdown: str

    def assert_owner(self, user_id: str) -> None:
        if self.owner_id != user_id:
            raise PermissionError("report belongs to another user")


@dataclass(frozen=True, slots=True)
class SQLiteRiskReportRepository:
    database_path: Path

    def __post_init__(self) -> None:
        path = Path(self.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        object.__setattr__(self, "database_path", path)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS risk_reports (
                    report_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    report_hash TEXT NOT NULL,
                    markdown_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    markdown TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(owner_id, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS risk_report_owner_idx ON risk_reports(owner_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS risk_report_snapshot_idx ON risk_reports(snapshot_id, created_at DESC);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def _decode(row: sqlite3.Row) -> StoredRiskReport:
        return StoredRiskReport(
            report_id=row["report_id"], owner_id=row["owner_id"],
            snapshot_id=row["snapshot_id"], idempotency_key=row["idempotency_key"],
            request_hash=row["request_hash"], payload=json.loads(row["payload_json"]),
            markdown=row["markdown"],
        )

    def get(self, report_id: str) -> StoredRiskReport:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM risk_reports WHERE report_id = ?", (report_id,)).fetchone()
        if row is None:
            raise LookupError("report not found")
        return self._decode(row)

    def list_for_owner(self, owner_id: str, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT report_id, snapshot_id, report_hash, created_at, payload_json
                FROM risk_reports
                WHERE owner_id = ?
                ORDER BY created_at DESC, report_id DESC
                LIMIT ?
                """,
                (owner_id, limit),
            ).fetchall()
        result = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            result.append({
                "report_id": row["report_id"], "snapshot_id": row["snapshot_id"],
                "stock": payload["stock"], "as_of": payload["as_of"],
                "schema_version": payload["schema_version"],
                "rule_version": payload["rule_version"],
                "report_hash": row["report_hash"], "created_at": row["created_at"],
            })
        return result

    def save(self, report: StoredRiskReport) -> tuple[StoredRiskReport, bool]:
        payload_json = json.dumps(report.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO risk_reports (
                        report_id, owner_id, snapshot_id, idempotency_key,
                        request_hash, report_hash, markdown_hash, payload_json, markdown
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        report.report_id, report.owner_id, report.snapshot_id,
                        report.idempotency_key, report.request_hash,
                        report.payload["report_hash"], report.payload["markdown_hash"],
                        payload_json, report.markdown,
                    ),
                )
            return report, True
        except sqlite3.IntegrityError as exc:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM risk_reports WHERE owner_id = ? AND idempotency_key = ?",
                    (report.owner_id, report.idempotency_key),
                ).fetchone()
            if row is None:
                raise
            existing = self._decode(row)
            if existing.request_hash != report.request_hash:
                raise DuplicateReportRequestError("idempotency_key was already used with different report inputs") from exc
            return existing, False

