import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from riskpilot.harness.context import ProductScenario, RuntimeContext
from riskpilot.infrastructure.leaderboard_store import SQLiteLeaderboardRepository
from riskpilot.infrastructure.replay_sessions import SQLiteReplaySessionRepository
from riskpilot.tools import (
    DrawHistoryCaseTool,
    GetLeaderboardTool,
    SubmitReplayActionTool,
    SubmitReplayScoreTool,
)


class ScoringToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database = Path(self.temp_dir.name) / "riskpilot.sqlite3"
        self.sessions = SQLiteReplaySessionRepository(database)
        self.leaderboard = SQLiteLeaderboardRepository(database)
        self.context = self.context_for("internal-user-001")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def context_for(user_id: str) -> RuntimeContext:
        return RuntimeContext(
            user_id=user_id,
            entrypoint="unit-test",
            scenario=ProductScenario.CONSUMER_EDUCATION,
            as_of=datetime(2025, 4, 30, tzinfo=timezone.utc),
        )

    def create_experiment(self, context: RuntimeContext, finish: bool = True) -> str:
        created = DrawHistoryCaseTool(self.sessions).invoke(
            context,
            {
                "stock_code": "601318",
                "decision_mode": "monthly",
                "capital": 100000,
                "max_loss": 90000,
            },
        )
        self.assertTrue(created.success, created.error)
        experiment_id = created.data["experiment_id"]
        if finish:
            submit = SubmitReplayActionTool(self.sessions)
            for step in range(4):
                response = submit.invoke(
                    context,
                    {
                        "experiment_id": experiment_id,
                        "expected_step": step,
                        "target_value": None,
                        "idempotency_key": f"{experiment_id}-{step}",
                    },
                )
                self.assertTrue(response.success, response.error)
        return experiment_id

    def submit_score(self, context: RuntimeContext, experiment_id: str, name: str = "同名玩家"):
        return SubmitReplayScoreTool(self.sessions, self.leaderboard).invoke(
            context,
            {
                "experiment_id": experiment_id,
                "display_name": name,
                "avatar": "🎮",
                "faction": "jin",
                "pnl": 999999,
                "pnl_pct": 999,
            },
        )

    def test_score_is_replayed_and_client_numbers_are_ignored(self) -> None:
        experiment_id = self.create_experiment(self.context)
        response = self.submit_score(self.context, experiment_id)
        self.assertTrue(response.success, response.error)
        self.assertEqual(response.data["score"]["pnl"], 0)
        self.assertEqual(response.data["score"]["pnl_pct"], 0)
        stored = self.leaderboard.score_for_experiment(experiment_id)
        self.assertEqual(stored["user_id"], self.context.user_id)

    def test_unfinished_foreign_duplicate_and_tampered_scores_are_rejected(self) -> None:
        unfinished = self.create_experiment(self.context, finish=False)
        self.assertEqual(self.submit_score(self.context, unfinished).error.code, "score_rejected")

        finished = self.create_experiment(self.context)
        foreign = self.submit_score(self.context_for("other-user"), finished)
        self.assertEqual(foreign.error.code, "forbidden")
        self.assertTrue(self.submit_score(self.context, finished).success)
        self.assertEqual(self.submit_score(self.context, finished).error.code, "duplicate_score")

        tampered_id = self.create_experiment(self.context)
        experiment = self.sessions.get(tampered_id)
        result = dict(experiment.latest_result)
        account = dict(result["account"])
        account["pnl"] = 999999
        result["account"] = account
        self.sessions.save(replace(experiment, latest_result=result))
        self.assertEqual(self.submit_score(self.context, tampered_id).error.code, "score_rejected")

    def test_same_display_name_keeps_distinct_internal_users(self) -> None:
        other = self.context_for("internal-user-002")
        first_id = self.create_experiment(self.context)
        second_id = self.create_experiment(other)
        self.assertTrue(self.submit_score(self.context, first_id).success)
        self.assertTrue(self.submit_score(other, second_id).success)

        board = GetLeaderboardTool(self.leaderboard).invoke(self.context, {"limit": 20})
        self.assertTrue(board.success)
        self.assertEqual(board.data["total_players"], 2)
        self.assertEqual({item["user_id"] for item in board.data["players"]},
                         {"internal-user-001", "internal-user-002"})
        self.assertEqual({item["display_name"] for item in board.data["players"]}, {"同名玩家"})

    def test_one_best_row_per_user_and_display_name_filtering(self) -> None:
        for _ in range(2):
            experiment_id = self.create_experiment(self.context)
            self.assertTrue(self.submit_score(self.context, experiment_id, "  玩家 一  ").success)
        board = self.leaderboard.leaderboard()
        self.assertEqual(len(board["players"]), 1)
        self.assertEqual(board["players"][0]["games"], 2)
        self.assertEqual(board["players"][0]["display_name"], "玩家 一")

        invalid_id = self.create_experiment(self.context)
        invalid = self.submit_score(self.context, invalid_id, "<script>")
        self.assertEqual(invalid.error.code, "score_rejected")


if __name__ == "__main__":
    unittest.main()

