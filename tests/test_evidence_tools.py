import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from riskpilot.harness.context import ProductScenario, RuntimeContext
from riskpilot.infrastructure.evidence_store import ReplayEvidenceRepository
from riskpilot.tools import ExtractRiskInputsTool, GetVisibleSnapshotTool, VerifyEvidenceTool
from backend.risk_engine import calculate_atr_from_closes, find_key_support


class EvidenceToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        folder = root / "600000"
        folder.mkdir()
        visible_lines = [
            f"2025-04-{day:02d},{day},{day + 0.5},{day + 0.6},{day - 0.1},{1000 + day}"
            for day in range(16, 31)
        ]
        price_bytes = (
            "日期,开盘,收盘,最高,最低,成交量\n"
            + "\n".join(visible_lines)
            + "\n2025-05-06,31,31.5,31.6,30.9,1200\n"
        ).encode("utf-8")
        (folder / "price_daily.csv").write_bytes(price_bytes)
        manifest = {
            "code": "600000",
            "name": "时间边界样本",
            "upstream": "test fixture",
            "source_urls": ["https://example.test/source"],
            "price_file": "price_daily.csv",
            "documents": [
                {"published_date": "2025-04-20", "title": "可见公告"},
                {"published_date": "2025-05-02", "title": "未来公告"},
            ],
            "dividends": [
                {"record_date": "2025-04-28", "gross_per_share": 0.1},
                {"record_date": "2025-05-09", "gross_per_share": 0.2},
            ],
            "sha256": {"price_daily.csv": hashlib.sha256(price_bytes).hexdigest()},
        }
        self.manifest_path = folder / "manifest.json"
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.price_path = folder / "price_daily.csv"
        self.repository = ReplayEvidenceRepository(root)
        self.context = RuntimeContext(
            user_id="evidence-test-user",
            entrypoint="unit-test",
            scenario=ProductScenario.CONSUMER_EDUCATION,
            as_of=datetime(2025, 4, 30, 15, 0, tzinfo=timezone.utc),
            snapshot_id="600000-2025-04-30",
            trace_id="trace-evidence-test",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_snapshot_never_returns_future_prices_documents_or_dividends(self) -> None:
        response = GetVisibleSnapshotTool(self.repository).invoke(
            self.context, {"stock_code": "600000"}
        )
        self.assertTrue(response.success)
        dates = [row["日期"] for row in response.data["prices"]]
        self.assertEqual(len(dates), 15)
        self.assertEqual(dates[-1], "2025-04-30")
        self.assertTrue(all(date <= "2025-04-30" for date in dates))
        self.assertEqual([item["title"] for item in response.data["documents"]], ["可见公告"])
        self.assertEqual(len(response.data["dividends"]), 1)
        self.assertEqual(response.meta.snapshot_id, "600000-2025-04-30")
        self.assertEqual(response.meta.rule_version, "evidence-v1")

    def test_context_rejects_mismatched_snapshot_identity(self) -> None:
        wrong_context = RuntimeContext(
            user_id="user",
            entrypoint="unit-test",
            scenario=ProductScenario.RESEARCH_SANDBOX,
            as_of=self.context.as_of,
            snapshot_id="600000-2025-05-06",
        )
        response = GetVisibleSnapshotTool(self.repository).invoke(
            wrong_context, {"stock_code": "600000"}
        )
        self.assertFalse(response.success)
        self.assertEqual(response.error.code, "evidence_unavailable")

    def test_hash_verification_detects_tampering(self) -> None:
        tool = VerifyEvidenceTool(self.repository)
        self.assertTrue(tool.invoke(self.context, {"stock_code": "600000"}).success)
        self.price_path.write_text("tampered", encoding="utf-8")
        response = tool.invoke(self.context, {"stock_code": "600000"})
        self.assertFalse(response.success)
        self.assertEqual(response.error.code, "evidence_integrity_failed")
        self.assertFalse(response.data["files"][0]["valid"])

    def test_repository_rejects_path_traversal(self) -> None:
        response = VerifyEvidenceTool(self.repository).invoke(
            self.context, {"stock_code": "../../etc/passwd"}
        )
        self.assertFalse(response.success)
        self.assertEqual(response.error.code, "evidence_unavailable")

    def test_extract_risk_inputs_matches_v1_algorithms(self) -> None:
        response = ExtractRiskInputsTool(self.repository).invoke(
            self.context, {"stock_code": "600000"}
        )
        self.assertTrue(response.success)
        snapshot = self.repository.visible_snapshot("600000", "2025-04-30")
        highs = [float(row["最高"]) for row in snapshot["prices"]]
        lows = [float(row["最低"]) for row in snapshot["prices"]]
        closes = [float(row["收盘"]) for row in snapshot["prices"]]
        self.assertEqual(response.data["current_price"], closes[-1])
        self.assertEqual(
            response.data["atr_14"],
            calculate_atr_from_closes(highs, lows, closes, 14),
        )
        self.assertEqual(response.data["key_support"], find_key_support(closes, 20))
        self.assertEqual(response.meta.rule_version, "market-features-v1")

    def test_future_price_changes_cannot_change_extracted_inputs(self) -> None:
        tool = ExtractRiskInputsTool(self.repository)
        baseline = tool.invoke(self.context, {"stock_code": "600000"})

        lines = self.price_path.read_text(encoding="utf-8").splitlines()
        lines[-1] = "2025-05-06,98,99,100,97,9999"
        changed = ("\n".join(lines) + "\n").encode("utf-8")
        self.price_path.write_bytes(changed)
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest["sha256"]["price_daily.csv"] = hashlib.sha256(changed).hexdigest()
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        mutated = tool.invoke(self.context, {"stock_code": "600000"})
        self.assertTrue(mutated.success)
        self.assertEqual(mutated.data, baseline.data)


if __name__ == "__main__":
    unittest.main()

