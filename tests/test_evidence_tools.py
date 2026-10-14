import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from riskpilot.harness.context import ProductScenario, RuntimeContext
from riskpilot.infrastructure.evidence_store import ReplayEvidenceRepository
from riskpilot.tools import GetVisibleSnapshotTool, VerifyEvidenceTool


class EvidenceToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        folder = root / "600000"
        folder.mkdir()
        price_bytes = (
            "日期,开盘,收盘,最高,最低,成交量\n"
            "2025-04-30,10,10.5,10.6,9.9,1000\n"
            "2025-05-06,10.6,11,11.2,10.5,1200\n"
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
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
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
        self.assertEqual([row["日期"] for row in response.data["prices"]], ["2025-04-30"])
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


if __name__ == "__main__":
    unittest.main()

