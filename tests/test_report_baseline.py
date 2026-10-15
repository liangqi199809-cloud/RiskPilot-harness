"""Golden V1 report behavior that V2 must preserve or change explicitly."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import unittest

from backend.main import AnalyzeRequest, analyze
from backend.report import verify_hash


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "report_baseline.json"
TOP_LEVEL_SECTIONS = {
    "agent_analyses", "backtest", "disclaimer", "evidence_pack", "fees",
    "human_confirmation_points", "invalidation_conditions", "limitations",
    "market_environment", "plain_language_summary", "report_hash", "report_meta",
    "risk_calculation", "risk_reward", "standard_scenario", "stress_tests",
    "system_status", "trading_plan", "user_input",
}


def project(result) -> dict:
    report = result.report
    return {
        "current_price": report["user_input"]["current_price"],
        "status": report["system_status"]["status"],
        "vetoed": report["system_status"]["vetoed"],
        "final_shares": report["risk_calculation"]["final_shares"],
        "stop_loss_price": report["risk_calculation"]["stop_loss_price"],
        "final_position_value": report["risk_calculation"]["final_position_value"],
        "final_position_ratio": report["risk_calculation"]["final_position_ratio"],
        "standard_loss": report["standard_scenario"]["standard_loss"],
        "risk_reward_ratio": report["risk_reward"]["risk_reward_ratio"],
        "stress_losses": [item["actual_loss"] for item in report["stress_tests"]],
        "is_synthetic": report["report_meta"]["data_snapshot"]["is_synthetic"],
        "daily_points": len(result.daily_data or []),
    }


class ReportBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.results = {}
        for name, case in cls.cases.items():
            cls.results[name] = asyncio.run(
                analyze(AnalyzeRequest(**case["request"], agent_mode="preset_demo"))
            )

    def test_four_representative_report_numbers_are_frozen(self):
        for name, case in self.cases.items():
            with self.subTest(case=name):
                result = self.results[name]
                self.assertTrue(result.success, result.error)
                self.assertEqual(project(result), case["expected"])

    def test_report_contract_keeps_all_rendered_sections(self):
        for name, result in self.results.items():
            with self.subTest(case=name):
                self.assertEqual(set(result.report), TOP_LEVEL_SECTIONS)
                self.assertEqual(result.report["report_meta"]["agent_execution"]["mode"], "preset_demo")
                self.assertEqual(result.report["report_meta"]["agent_execution"]["run_status"], "PRESET_DEMO")
                for perspective in ("technical", "fundamental", "news", "capital_flow"):
                    self.assertTrue(result.report["agent_analyses"].get(perspective))

    def test_markdown_and_hash_integrity_behavior_is_frozen(self):
        for name, result in self.results.items():
            with self.subTest(case=name):
                self.assertTrue(result.report_markdown.startswith("# RiskPilot 模拟研究报告\n"))
                self.assertIn("## 确定性风险计算", result.report_markdown)
                self.assertEqual(len(result.report["report_hash"]), 64)
                self.assertTrue(verify_hash(result.report))
                tampered = deepcopy(result.report)
                tampered["risk_calculation"]["final_shares"] += 100
                self.assertFalse(verify_hash(tampered))

    def test_missing_evidence_is_disclosed_instead_of_fabricated(self):
        analyses = self.results["insufficient_evidence"].report["agent_analyses"]
        self.assertIn("未包含结构化财务字段", analyses["fundamental"])
        self.assertIn("不应形成真实公司基本面结论", analyses["fundamental"])
        self.assertIn("未包含公告数据", analyses["news"])
        self.assertIn("无法进行事件驱动分析", analyses["news"])

    def test_synthetic_sample_is_visibly_labelled(self):
        result = self.results["synthetic_standard"]
        self.assertTrue(result.report["report_meta"]["data_snapshot"]["is_synthetic"])
        self.assertIn("合成演示数据", result.report["user_input"]["stock_name"])


if __name__ == "__main__":
    unittest.main()
