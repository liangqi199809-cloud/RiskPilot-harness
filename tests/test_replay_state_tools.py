import unittest
from datetime import datetime, timezone
import tempfile
from pathlib import Path

from backend.replay import Action, ReplayRequest, replay
from riskpilot.harness.context import ProductScenario, RuntimeContext
from riskpilot.infrastructure.replay_sessions import (
    InMemoryReplaySessionRepository,
    SQLiteReplaySessionRepository,
)
from riskpilot.tools import (
    DrawHistoryCaseTool,
    PreviewReplayPositionTool,
    SubmitReplayActionTool,
)


class ReplayStateToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sessions = InMemoryReplaySessionRepository()
        self.draw = DrawHistoryCaseTool(self.sessions)
        self.preview = PreviewReplayPositionTool(self.sessions)
        self.submit = SubmitReplayActionTool(self.sessions)
        self.owner = RuntimeContext(
            user_id="owner-001",
            entrypoint="unit-test",
            scenario=ProductScenario.CONSUMER_EDUCATION,
            as_of=datetime(2025, 4, 30, tzinfo=timezone.utc),
            trace_id="trace-replay-owner",
        )
        self.other_user = RuntimeContext(
            user_id="other-002",
            entrypoint="unit-test",
            scenario=ProductScenario.CONSUMER_EDUCATION,
            as_of=self.owner.as_of,
            trace_id="trace-replay-other",
        )

    def create(self, mode: str = "monthly") -> dict:
        response = self.draw.invoke(
            self.owner,
            {
                "stock_code": "601318",
                "decision_mode": mode,
                "capital": 100000,
                "max_loss": 90000,
            },
        )
        self.assertTrue(response.success, response.error)
        return response.data

    def test_create_and_preview_does_not_change_server_state(self) -> None:
        created = self.create()
        experiment_id = created["experiment_id"]
        self.assertEqual(created["state"], "decision_pending")
        self.assertEqual(created["step"], 0)
        self.assertEqual(created["total_decisions"], 4)

        preview = self.preview.invoke(
            self.owner,
            {"experiment_id": experiment_id, "expected_step": 0, "target_value": 50000},
        )
        self.assertTrue(preview.success)
        self.assertGreater(preview.data["preview"]["preview_shares"], 0)
        self.assertEqual(self.sessions.get(experiment_id).step, 0)

        preview.data["account"]["cash"] = -1
        self.assertEqual(self.sessions.get(experiment_id).latest_result["account"]["cash"], 100000)

    def test_other_user_cannot_preview_or_submit(self) -> None:
        experiment_id = self.create()["experiment_id"]
        preview = self.preview.invoke(
            self.other_user,
            {"experiment_id": experiment_id, "expected_step": 0, "target_value": 10000},
        )
        submit = self.submit.invoke(
            self.other_user,
            {"experiment_id": experiment_id, "expected_step": 0, "target_value": None, "idempotency_key": "other-1"},
        )
        self.assertEqual(preview.error.code, "forbidden")
        self.assertEqual(submit.error.code, "forbidden")
        self.assertEqual(self.sessions.get(experiment_id).step, 0)

    def test_skip_and_duplicate_submissions_are_rejected(self) -> None:
        experiment_id = self.create()["experiment_id"]
        skipped = self.submit.invoke(
            self.owner,
            {"experiment_id": experiment_id, "expected_step": 2, "target_value": None, "idempotency_key": "step-2"},
        )
        self.assertFalse(skipped.success)

        first = self.submit.invoke(
            self.owner,
            {"experiment_id": experiment_id, "expected_step": 0, "target_value": None, "idempotency_key": "step-0"},
        )
        duplicate = self.submit.invoke(
            self.owner,
            {"experiment_id": experiment_id, "expected_step": 0, "target_value": None, "idempotency_key": "step-0"},
        )
        self.assertTrue(first.success)
        self.assertFalse(duplicate.success)
        self.assertEqual(self.sessions.get(experiment_id).step, 1)

    def test_monthly_finish_is_immutable_and_matches_v1(self) -> None:
        experiment_id = self.create()["experiment_id"]
        final = None
        actions = [50000, None, 20000, 0]
        for step, target in enumerate(actions):
            final = self.submit.invoke(
                self.owner,
                {"experiment_id": experiment_id, "expected_step": step, "target_value": target, "idempotency_key": f"monthly-{step}"},
            )
            self.assertTrue(final.success, final.error)
        self.assertEqual(final.data["state"], "finished")
        expected = replay(
            ReplayRequest(
                stock_code="601318",
                decision_mode="monthly",
                capital=100000,
                max_loss=90000,
                actions=[Action(target_value=value) for value in actions],
            )
        )
        self.assertEqual(final.data["account"], expected["account"])

        after_finish = self.submit.invoke(
            self.owner,
            {"experiment_id": experiment_id, "expected_step": 4, "target_value": None, "idempotency_key": "too-late"},
        )
        self.assertFalse(after_finish.success)
        self.assertIn("finished", after_finish.error.message)

    def test_weekly_seventeen_steps_match_v1_and_can_resume(self) -> None:
        experiment_id = self.create("weekly")["experiment_id"]
        actions = [50000] + [None] * 16
        for step, target in enumerate(actions[:8]):
            response = self.submit.invoke(
                self.owner,
                {"experiment_id": experiment_id, "expected_step": step, "target_value": target, "idempotency_key": f"weekly-{step}"},
            )
            self.assertTrue(response.success, response.error)

        # A new tool instance recovers the same server-side session repository.
        resumed_tool = SubmitReplayActionTool(self.sessions)
        for step, target in enumerate(actions[8:], start=8):
            response = resumed_tool.invoke(
                self.owner,
                {"experiment_id": experiment_id, "expected_step": step, "target_value": target, "idempotency_key": f"weekly-{step}"},
            )
            self.assertTrue(response.success, response.error)

        expected = replay(
            ReplayRequest(
                stock_code="601318",
                decision_mode="weekly",
                capital=100000,
                max_loss=90000,
                actions=[Action(target_value=value) for value in actions],
            )
        )
        self.assertEqual(response.data["step"], 17)
        self.assertEqual(response.data["state"], "finished")
        self.assertEqual(response.data["account"], expected["account"])

    def test_sqlite_survives_repository_restart_and_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "riskpilot.sqlite3"
            first_repository = SQLiteReplaySessionRepository(database)
            created = DrawHistoryCaseTool(first_repository).invoke(
                self.owner,
                {
                    "stock_code": "601318",
                    "decision_mode": "monthly",
                    "capital": 100000,
                    "max_loss": 90000,
                },
            )
            experiment_id = created.data["experiment_id"]
            first = SubmitReplayActionTool(first_repository).invoke(
                self.owner,
                {
                    "experiment_id": experiment_id,
                    "expected_step": 0,
                    "target_value": 50000,
                    "idempotency_key": "persistent-step-0",
                },
            )
            self.assertTrue(first.success)

            # Constructing a new repository simulates a process restart.
            restarted_repository = SQLiteReplaySessionRepository(database)
            restored = restarted_repository.get(experiment_id)
            self.assertEqual(restored.step, 1)
            self.assertEqual(restored.owner_id, self.owner.user_id)
            self.assertIn("persistent-step-0", restored.idempotency_keys)

            resumed = SubmitReplayActionTool(restarted_repository).invoke(
                self.owner,
                {
                    "experiment_id": experiment_id,
                    "expected_step": 1,
                    "target_value": None,
                    "idempotency_key": "persistent-step-1",
                },
            )
            self.assertTrue(resumed.success)
            self.assertEqual(resumed.data["step"], 2)

            backup_path = restarted_repository.backup_to(Path(directory) / "backup.sqlite3")
            backup_repository = SQLiteReplaySessionRepository(backup_path)
            self.assertEqual(backup_repository.get(experiment_id).step, 2)


if __name__ == "__main__":
    unittest.main()

