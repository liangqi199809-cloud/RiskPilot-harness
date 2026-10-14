import json
import unittest
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import riskpilot
from riskpilot.harness.context import ProductScenario, RuntimeContext
from riskpilot.harness.registry import DuplicateToolError, ToolNotFoundError, ToolRegistry
from riskpilot.harness.responses import ErrorDetail, ToolMeta, ToolResponse
from riskpilot.policies import PolicyDecision


@dataclass
class EchoTool:
    name: str = "echo"
    version: str = "1.0.0"

    def invoke(self, context: RuntimeContext, arguments: dict[str, Any]) -> ToolResponse[dict[str, Any]]:
        return ToolResponse(
            success=True,
            data=arguments,
            meta=ToolMeta(
                tool_name=self.name,
                tool_version=self.version,
                rule_version="none",
                snapshot_id=context.snapshot_id,
                trace_id=context.trace_id,
            ),
        )


class HarnessSkeletonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = RuntimeContext(
            user_id="anonymous-test-user",
            entrypoint="unit-test",
            scenario=ProductScenario.PORTFOLIO_DEMO,
            as_of=datetime(2025, 8, 29, tzinfo=timezone.utc),
            snapshot_id="test-snapshot",
        )

    def test_public_package_is_importable(self) -> None:
        self.assertEqual(riskpilot.__version__, "2.0.0.dev0")
        self.assertIs(riskpilot.RuntimeContext, RuntimeContext)

    def test_context_requires_timezone_aware_as_of(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone"):
            RuntimeContext(
                user_id="user",
                entrypoint="test",
                scenario=ProductScenario.RESEARCH_SANDBOX,
                as_of=datetime(2025, 8, 29),
            )

    def test_registry_invokes_registered_tool(self) -> None:
        registry = ToolRegistry()
        registry.register(EchoTool())
        response = registry.invoke("echo", self.context, {"value": 7})
        self.assertTrue(response.success)
        self.assertEqual(response.data, {"value": 7})
        self.assertEqual(response.meta.trace_id, self.context.trace_id)
        self.assertEqual(registry.names(), ("echo",))

    def test_registry_rejects_duplicate_and_unknown_tools(self) -> None:
        registry = ToolRegistry()
        registry.register(EchoTool())
        with self.assertRaises(DuplicateToolError):
            registry.register(EchoTool())
        with self.assertRaises(ToolNotFoundError):
            registry.get("missing")

    def test_response_contract_is_json_serializable(self) -> None:
        response = ToolResponse(
            success=False,
            data=None,
            meta=ToolMeta(
                tool_name="echo",
                tool_version="1.0.0",
                rule_version="none",
                snapshot_id=None,
                trace_id=self.context.trace_id,
            ),
            error=ErrorDetail(code="invalid_input", message="bad value"),
        )
        self.assertIn("invalid_input", json.dumps(response.to_dict()))

    def test_policy_decision_is_explicit(self) -> None:
        decision = PolicyDecision(allowed=False, reason="not authorized")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "not authorized")


if __name__ == "__main__":
    unittest.main()

