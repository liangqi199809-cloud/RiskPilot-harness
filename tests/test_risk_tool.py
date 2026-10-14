import unittest
from dataclasses import asdict
from datetime import datetime, timezone

from backend.risk_engine import UserInput, calculate_position, run_stress_tests
from riskpilot.domain.risk import RiskBudgetInput, calculate_risk_budget
from riskpilot.harness.context import ProductScenario, RuntimeContext
from riskpilot.harness.registry import ToolRegistry
from riskpilot.tools import CalculateRiskBudgetTool


class RiskToolParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = RuntimeContext(
            user_id="parity-test-user",
            entrypoint="unit-test",
            scenario=ProductScenario.CONSUMER_EDUCATION,
            as_of=datetime(2025, 8, 29, tzinfo=timezone.utc),
            snapshot_id="601318-2025-08-29",
            trace_id="trace-parity-test",
        )

    def assert_parity(self, values: dict) -> None:
        legacy_input = UserInput(**values)
        legacy_position = calculate_position(legacy_input)
        legacy_stress = run_stress_tests(legacy_input, legacy_position)

        result = calculate_risk_budget(RiskBudgetInput(**values))

        self.assertEqual(result.position, asdict(legacy_position))
        self.assertEqual(result.stress_tests, tuple(asdict(item) for item in legacy_stress))

    def test_standard_case_matches_v1_field_for_field(self) -> None:
        self.assert_parity(
            {
                "stock_code": "601318",
                "stock_name": "主板样本 B",
                "capital": 100000,
                "max_loss": 3000,
                "current_price": 45,
                "atr_14": 1.2,
                "key_support": 43,
            }
        )

    def test_vetoed_case_matches_v1_field_for_field(self) -> None:
        self.assert_parity(
            {
                "stock_code": "600519",
                "stock_name": "主板样本 A",
                "capital": 100000,
                "max_loss": 3000,
                "current_price": 1700,
                "atr_14": 35,
                "key_support": 1650,
            }
        )

    def test_high_risk_and_growth_board_cases_match_v1(self) -> None:
        cases = [
            {
                "stock_code": "601318",
                "stock_name": "高风险样本",
                "capital": 100000,
                "max_loss": 8000,
                "current_price": 45,
                "atr_14": 1.2,
                "key_support": 43,
            },
            {
                "stock_code": "300001",
                "stock_name": "创业板样本",
                "capital": 200000,
                "max_loss": 5000,
                "current_price": 20,
                "atr_14": 0.9,
                "key_support": 18.5,
                "board": "growth",
            },
        ]
        for values in cases:
            with self.subTest(stock_code=values["stock_code"]):
                self.assert_parity(values)

    def test_tool_returns_versioned_traceable_envelope(self) -> None:
        registry = ToolRegistry()
        registry.register(CalculateRiskBudgetTool())
        response = registry.invoke(
            "calculate_risk_budget",
            self.context,
            {
                "stock_code": "601318",
                "stock_name": "主板样本 B",
                "capital": 100000,
                "max_loss": 3000,
                "current_price": 45,
                "atr_14": 1.2,
                "key_support": 43,
            },
        )
        self.assertTrue(response.success)
        self.assertEqual(response.meta.tool_version, "1.0.0")
        self.assertEqual(response.meta.rule_version, "risk-v1")
        self.assertEqual(response.meta.snapshot_id, "601318-2025-08-29")
        self.assertEqual(response.meta.trace_id, "trace-parity-test")
        self.assertEqual(response.data["position"]["final_shares"], 600)

    def test_tool_returns_structured_validation_error(self) -> None:
        response = CalculateRiskBudgetTool().invoke(
            self.context,
            {
                "stock_code": "601318",
                "stock_name": "无效样本",
                "capital": 1000,
                "max_loss": 2000,
                "current_price": 45,
                "atr_14": 1.2,
                "key_support": 43,
            },
        )
        self.assertFalse(response.success)
        self.assertEqual(response.error.code, "invalid_input")
        self.assertIn("不得超过本金", response.error.message)


if __name__ == "__main__":
    unittest.main()

