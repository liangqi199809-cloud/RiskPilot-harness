"""SQLite persistence for internal users and verified replay scores."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Any

from riskpilot.domain.scoring import ReplayScore, UserProfile


class DuplicateScoreError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SQLiteLeaderboardRepository:
    database_path: Path

    def __post_init__(self) -> None:
        path = Path(self.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        object.__setattr__(self, "database_path", path)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    avatar TEXT NOT NULL,
                    faction TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS replay_scores (
                    score_id TEXT PRIMARY KEY,
                    experiment_id TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    stock_code TEXT NOT NULL,
                    stock_name TEXT NOT NULL,
                    decision_mode TEXT NOT NULL,
                    capital REAL NOT NULL,
                    pnl REAL NOT NULL,
                    pnl_pct REAL NOT NULL,
                    faction TEXT NOT NULL,
                    submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );
                CREATE INDEX IF NOT EXISTS score_user_idx
                    ON replay_scores(user_id, pnl_pct DESC);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def save_verified_score(self, profile: UserProfile, score: ReplayScore) -> None:
        if profile.user_id != score.user_id:
            raise ValueError("profile and score user_id must match")
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO users (user_id, display_name, avatar, faction)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        display_name = excluded.display_name,
                        avatar = excluded.avatar,
                        faction = excluded.faction,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (profile.user_id, profile.display_name, profile.avatar, profile.faction),
                )
                connection.execute(
                    """
                    INSERT INTO replay_scores (
                        score_id, experiment_id, user_id, stock_code, stock_name,
                        decision_mode, capital, pnl, pnl_pct, faction
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        score.score_id,
                        score.experiment_id,
                        score.user_id,
                        score.stock_code,
                        score.stock_name,
                        score.decision_mode,
                        score.capital,
                        score.pnl,
                        score.pnl_pct,
                        score.faction,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if "experiment_id" in str(exc) or "UNIQUE" in str(exc):
                raise DuplicateScoreError("score already submitted for this experiment") from exc
            raise

    def leaderboard(self, limit: int = 20) -> dict[str, Any]:
        limit = max(1, min(int(limit), 100))
        with self._connect() as connection:
            rows = connection.execute(
                """
                WITH ranked AS (
                    SELECT s.*, u.display_name, u.avatar,
                           COUNT(*) OVER (PARTITION BY s.user_id) AS games,
                           ROW_NUMBER() OVER (
                               PARTITION BY s.user_id
                               ORDER BY s.pnl_pct DESC, s.submitted_at ASC
                           ) AS user_best
                    FROM replay_scores s
                    JOIN users u ON u.user_id = s.user_id
                )
                SELECT * FROM ranked
                WHERE user_best = 1
                ORDER BY pnl_pct DESC, submitted_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            total = connection.execute(
                "SELECT COUNT(DISTINCT user_id) FROM replay_scores"
            ).fetchone()[0]
        players = []
        for rank, row in enumerate(rows, start=1):
            players.append(
                {
                    "rank": rank,
                    "user_id": row["user_id"],
                    "display_name": row["display_name"],
                    "avatar": row["avatar"],
                    "faction": row["faction"],
                    "pnl_pct": row["pnl_pct"],
                    "games": row["games"],
                    "stock_code": row["stock_code"],
                }
            )
        return {"players": players, "total_players": total}

    def score_for_experiment(self, experiment_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM replay_scores WHERE experiment_id = ?", (experiment_id,)
            ).fetchone()
        return dict(row) if row else None

