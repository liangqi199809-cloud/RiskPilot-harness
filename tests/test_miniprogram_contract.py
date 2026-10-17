"""Static contract checks for the dependency-free native mini-program prototype."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "miniprogram"


class MiniProgramContractTests(unittest.TestCase):
    def test_declared_pages_have_native_page_files(self):
        app = json.loads((MINI / "app.json").read_text(encoding="utf-8"))
        self.assertEqual(
            app["pages"],
            ["pages/home/index", "pages/report/index", "pages/replay/index", "pages/settings/index"],
        )
        for page in app["pages"]:
            for suffix in (".js", ".json", ".wxml", ".wxss"):
                self.assertTrue((MINI / f"{page}{suffix}").is_file(), f"missing {page}{suffix}")

    def test_home_has_two_equal_product_entries(self):
        home = (MINI / "pages/home/index.wxml").read_text(encoding="utf-8")
        self.assertIn("风险报告", home)
        self.assertIn("时间穿越挑战", home)
        self.assertIn('bindtap="openReport"', home)
        self.assertIn('bindtap="openReplay"', home)

    def test_both_paths_use_v2_only_and_never_call_v1_analyze(self):
        source = "\n".join(path.read_text(encoding="utf-8") for path in MINI.rglob("*.js"))
        required = {
            "/api/v2/reports", "/api/v2/reports/query", "/api/v2/reports/integrity",
            "/api/v2/reports/list", "/api/v2/replay/cases", "/api/v2/replay/session",
            "/api/v2/replay/preview", "/api/v2/replay/actions",
            "/api/v2/replay/scores", "/api/v2/leaderboard/query",
        }
        for path in required:
            self.assertIn(path, source)
        self.assertNotIn("/api/analyze", source)
        self.assertNotIn("/api/report/", source)

    def test_report_mobile_order_starts_with_discipline_and_three_numbers(self):
        page = (MINI / "pages/report/index.wxml").read_text(encoding="utf-8")
        headings = ["01 · 风险纪律", "02 · 先看三个数字", "03 · 截止日之前的价格", "04 · 四个观察视角", "05 · 证据与完整性"]
        positions = [page.index(item) for item in headings]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("用同一股票进入时间穿越挑战", page)

    def test_development_token_is_not_hardcoded(self):
        source = "\n".join(path.read_text(encoding="utf-8") for path in MINI.rglob("*.js"))
        self.assertIn("riskpilot_dev_token", source)
        self.assertNotIn("owner-token", source)
        self.assertNotIn("RISKPILOT_API_TOKENS_JSON", source)

    def test_all_json_files_are_valid(self):
        for path in MINI.rglob("*.json"):
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

