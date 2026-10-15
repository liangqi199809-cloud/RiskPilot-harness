"""Tests for the governed Harness execution path."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from riskpilot.harness.context import ProductScenario, RuntimeContext
from riskpilot.harness.defaults import build_default_orchestrator
from riskpilot.harness.orchestrator import HarnessOrchestrator
from riskpilot.harness.registry import ToolRegistry
from riskpilot.harness.responses import ToolMeta, ToolResponse
from riskpilot.infrastructure.audit_store import SQLiteAuditRecorder
from riskpilot.policies.base import PolicyDecision
from riskpilot.policies.guards import ScenarioToolPolicy, SnapshotRequiredPolicy


class EchoTool:
    name = "get_leaderboard"
    version = "test-1"

    def invoke(self, context, arguments):
        return ToolResponse(
            success=True,
            data={"received": arguments},
            meta=ToolMeta(self.name, self.version, "test-rule", context.trace_id, context.snapshot_id),
        )


class ExplodingTool:
    name = "verify_evidence"
    version = "test-1"

    def invoke(self, context, arguments):
        raise RuntimeError("internal detail")


class DenyAfterPolicy:
    def before_call(self, context, tool_name, arguments):
        return PolicyDecision(True, warnings=("checked before",))

    def after_call(self, context, tool_name, response):
        return PolicyDecision(False, "result rejected", warnings=("checked after",))


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "audit.sqlite3"
        self.audit = SQLiteAuditRecorder(self.database_path)
        self.context = RuntimeContext(
            user_id="internal-user-1",
            entrypoint="wechat",
            scenario=ProductScenario.CONSUMER_EDUCATION,
            as_of=datetime(2025, 4, 30, tzinfo=timezone.utc),
            trace_id="trace-test-1",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def _orchestrator(self, tool, policies=()):
        registry = ToolRegistry()
        registry.register(tool)
        return HarnessOrchestrator(registry, policies, self.audit)

    def test_allowed_call_is_executed_and_audited(self):
        orchestrator = self._orchestrator(EchoTool(), (ScenarioToolPolicy(),))
        response = orchestrator.invoke("get_leaderboard", self.context, {"limit": 5})

        self.assertTrue(response.success)
        self.assertEqual(response.data["received"], {"limit": 5})
        records = self.audit.list_for_trace(self.context.trace_id)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].tool_name, "get_leaderboard")
        self.assertEqual(len(records[0].input_sha256), 64)
        self.assertTrue(records[0].success)

    def test_read_only_scenario_denies_game_mutation(self):
        tool = EchoTool()
        tool.name = "submit_replay_action"
        readonly = RuntimeContext(
            user_id="user-2", entrypoint="web",
            scenario=ProductScenario.PORTFOLIO_DEMO,
            as_of=self.context.as_of, trace_id="trace-denied",
        )
        response = self._orchestrator(tool, (ScenarioToolPolicy(),)).invoke(
            "submit_replay_action", readonly, {"target_value": 50000}
        )

        self.assertFalse(response.success)
        self.assertEqual(response.error.code, "policy_denied")
        self.assertEqual(self.audit.list_for_trace("trace-denied")[0].error_code, "policy_denied")

    def test_snapshot_policy_denies_unbound_calculation(self):
        tool = EchoTool()
        tool.name = "calculate_risk_budget"
        response = self._orchestrator(tool, (SnapshotRequiredPolicy(),)).invoke(
            "calculate_risk_budget", self.context, {"price": 10}
        )
        self.assertFalse(response.success)
        self.assertIn("requires snapshot_id", response.error.message)

    def test_unexpected_tool_failure_becomes_structured_response(self):
        response = self._orchestrator(ExplodingTool()).invoke(
            "verify_evidence", self.context, {"stock_code": "600030"}
        )
        self.assertFalse(response.success)
        self.assertEqual(response.error.code, "tool_execution_failed")
        self.assertNotIn("internal detail", response.error.message)
        self.assertEqual(self.audit.list_for_trace(self.context.trace_id)[0].error_code, "tool_execution_failed")

    def test_after_policy_can_hide_result_and_preserve_warnings(self):
        response = self._orchestrator(EchoTool(), (DenyAfterPolicy(),)).invoke(
            "get_leaderboard", self.context, {}
        )
        self.assertFalse(response.success)
        self.assertEqual(response.error.code, "policy_denied")
        self.assertEqual(response.warnings, ("checked before", "checked after"))

    def test_audit_database_does_not_store_raw_arguments(self):
        secret = "private-display-name"
        self._orchestrator(EchoTool()).invoke("get_leaderboard", self.context, {"name": secret})
        with sqlite3.connect(self.database_path) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(tool_audit)")}
            row = connection.execute("SELECT * FROM tool_audit").fetchone()
        self.assertNotIn("arguments", columns)
        self.assertNotIn("response_json", columns)
        self.assertNotIn(secret, "|".join(str(value) for value in row))

    def test_missing_tool_is_audited(self):
        registry = ToolRegistry()
        response = HarnessOrchestrator(registry, audit_recorder=self.audit).invoke(
            "missing", self.context, {}
        )
        self.assertFalse(response.success)
        self.assertEqual(response.error.code, "tool_not_found")
        self.assertEqual(self.audit.list_for_trace(self.context.trace_id)[0].tool_version, "unregistered")

    def test_default_runtime_registers_every_current_tool(self):
        runtime = build_default_orchestrator(self.database_path)
        self.assertEqual(
            runtime.registry.names(),
            (
                "calculate_risk_budget", "draw_history_case", "extract_risk_inputs",
                "get_leaderboard", "get_replay_session", "get_visible_snapshot", "preview_replay_position",
                "submit_replay_action", "submit_replay_score", "verify_evidence",
            ),
        )


if __name__ == "__main__":
    unittest.main()
