"""Tests for the model boundary and deterministic-result explanation guard."""

from __future__ import annotations

import unittest

from riskpilot.agents import ModelRequest, ModelResult, OfflineModelGateway, ToolResultExplainer
from riskpilot.harness.responses import ErrorDetail, ToolMeta, ToolResponse


class CapturingGateway:
    def __init__(self):
        self.request = None

    def generate(self, request):
        self.request = request
        return ModelResult(
            success=True, text="最大损失预算为3000元。", mode="live",
            provider="test", model="test-model", prompt_version=request.prompt_version,
        )


def response(success=True):
    meta = ToolMeta(
        tool_name="calculate_risk_budget", tool_version="1.0.0",
        rule_version="risk-v1", trace_id="trace-model-test",
        snapshot_id="600030-2025-04-30",
    )
    if success:
        return ToolResponse(success=True, data={"max_loss": 3000, "shares": 600}, meta=meta)
    return ToolResponse(
        success=False, data=None, meta=meta,
        error=ErrorDetail(code="invalid_input", message="bad input"),
    )


class ModelGatewayTests(unittest.TestCase):
    def test_offline_gateway_is_explicit_and_never_claims_ai_success(self):
        result = OfflineModelGateway().generate(
            ModelRequest("explain", "Do not change numbers", "result", "prompt-v1")
        )
        self.assertFalse(result.success)
        self.assertEqual(result.mode, "offline")
        self.assertEqual(result.error_code, "model_offline")
        self.assertIsNone(result.provider)
        self.assertIsNone(result.model)
        self.assertIn("不受影响", result.text)

    def test_explainer_sends_versioned_authoritative_tool_result(self):
        gateway = CapturingGateway()
        result = ToolResultExplainer(gateway).explain(response(), audience="小程序用户")
        self.assertTrue(result.success)
        self.assertEqual(gateway.request.task, "explain_tool_result")
        self.assertEqual(gateway.request.prompt_version, "tool-explanation-v1")
        self.assertIn('"max_loss":3000', gateway.request.input_text)
        self.assertIn('"snapshot_id":"600030-2025-04-30"', gateway.request.input_text)
        self.assertIn("不得修改", gateway.request.instructions)
        self.assertIn("小程序用户", gateway.request.input_text)

    def test_failed_tool_result_is_not_sent_to_model(self):
        gateway = CapturingGateway()
        with self.assertRaisesRegex(ValueError, "failed tool response"):
            ToolResultExplainer(gateway).explain(response(success=False))
        self.assertIsNone(gateway.request)

    def test_model_result_contract_rejects_ambiguous_states(self):
        with self.assertRaises(ValueError):
            ModelResult(True, "", "live", "test", "model", "v1")
        with self.assertRaises(ValueError):
            ModelResult(False, "notice", "offline", None, None, "v1")


if __name__ == "__main__":
    unittest.main()
