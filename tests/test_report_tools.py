"""R3 report assembly, persistence, ownership, and integrity tests."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from riskpilot.agents import PerspectiveResult
from riskpilot.harness.context import ProductScenario, RuntimeContext
from riskpilot.infrastructure.report_store import SQLiteRiskReportRepository
from riskpilot.tools.reports import BuildRiskReportTool, GetRiskReportTool, VerifyRiskReportIntegrityTool


def price_rows() -> list[dict]:
    rows = []
    for index in range(30):
        close = 10 + index * 0.08
        rows.append({
            "date": f"2025-03-{index + 1:02d}", "open": close - 0.02,
            "high": close + 0.2, "low": close - 0.2, "close": close,
            "volume": 10_000 + index * 100,
        })
    return rows


def unavailable_perspective(name: str) -> dict:
    return asdict(PerspectiveResult(
        perspective=name, status="unavailable", summary="AI解释当前不可用。",
        observations=(), risks=(), invalidation_conditions=(), uncertainties=("模型离线",),
        evidence_refs=(), prompt_version=f"report-{name}-v1", error_code="model_offline",
    ))


def report_arguments(key: str = "request-1") -> dict:
    return {
        "idempotency_key": key, "stock_code": "601318", "stock_name": "中国平安",
        "capital": 100_000, "max_loss": 3_000, "current_price": 12.32,
        "stop_price": 11.5, "shares": 1_000, "standard_loss": 900,
        "price_rows": price_rows(),
        "perspectives": {
            name: unavailable_perspective(name)
            for name in ("technical", "fundamental", "news")
        },
        "evidence": {"source": "verified-test-snapshot", "license_status": "review_required"},
    }


class ReportToolTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "reports.sqlite3"
        self.repository = SQLiteRiskReportRepository(self.database)
        self.build = BuildRiskReportTool(self.repository)
        self.get = GetRiskReportTool(self.repository)
        self.verify = VerifyRiskReportIntegrityTool(self.repository)
        self.owner = RuntimeContext(
            user_id="owner-001", entrypoint="unit-test",
            scenario=ProductScenario.CONSUMER_EDUCATION,
            as_of=datetime(2025, 3, 30, 15, tzinfo=timezone.utc),
            snapshot_id="601318-2025-03-30", trace_id="trace-report-owner",
        )
        self.other = RuntimeContext(
            user_id="other-002", entrypoint="unit-test",
            scenario=ProductScenario.CONSUMER_EDUCATION,
            as_of=self.owner.as_of, snapshot_id=self.owner.snapshot_id,
            trace_id="trace-report-other",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def create(self, key="request-1"):
        response = self.build.invoke(self.owner, report_arguments(key))
        self.assertTrue(response.success, response.error)
        return response

    def test_build_persists_complete_versioned_report_and_markdown(self):
        response = self.create()
        report = response.data["report"]
        self.assertTrue(response.data["created"])
        self.assertEqual(report["owner_id"], self.owner.user_id)
        self.assertEqual(report["snapshot_id"], self.owner.snapshot_id)
        self.assertEqual(report["schema_version"], "risk-report-v2")
        self.assertEqual(report["rule_version"], "risk-report-build-v1")
        self.assertEqual(report["deterministic_core"]["schema_version"], "report-domain-v1")
        self.assertEqual(set(report["perspectives"]), {"technical", "fundamental", "news"})
        self.assertEqual(len(report["report_hash"]), 64)
        self.assertEqual(len(report["markdown_hash"]), 64)
        self.assertIn("# RiskPilot 风险教育报告 V2", response.data["markdown"])
        self.assertNotIn("建议买入", response.data["markdown"])
        self.assertTrue(self.verify.invoke(self.owner, {"report_id": report["report_id"]}).data["valid"])

    def test_duplicate_request_returns_original_but_conflicting_reuse_fails(self):
        first = self.create()
        second = self.build.invoke(self.owner, report_arguments())
        self.assertTrue(second.success)
        self.assertFalse(second.data["created"])
        self.assertEqual(first.data["report"]["report_id"], second.data["report"]["report_id"])

        changed_explanation = report_arguments()
        changed_explanation["perspectives"]["technical"]["summary"] = "模型重试产生的不同措辞。"
        retried = self.build.invoke(self.owner, changed_explanation)
        self.assertTrue(retried.success)
        self.assertFalse(retried.data["created"])
        self.assertEqual(retried.data["report"]["report_id"], first.data["report"]["report_id"])

        changed = report_arguments()
        changed["max_loss"] = 2_500
        conflict = self.build.invoke(self.owner, changed)
        self.assertFalse(conflict.success)
        self.assertEqual(conflict.error.code, "idempotency_conflict")

    def test_same_fixed_request_has_same_report_id_in_a_fresh_store(self):
        first_id = self.create().data["report"]["report_id"]
        other_database = Path(self.temporary.name) / "fresh.sqlite3"
        fresh = BuildRiskReportTool(SQLiteRiskReportRepository(other_database))
        second = fresh.invoke(self.owner, report_arguments())
        self.assertTrue(second.success)
        self.assertEqual(second.data["report"]["report_id"], first_id)

    def test_cross_user_read_and_integrity_checks_are_forbidden(self):
        report_id = self.create().data["report"]["report_id"]
        read = self.get.invoke(self.other, {"report_id": report_id})
        verify = self.verify.invoke(self.other, {"report_id": report_id})
        self.assertEqual(read.error.code, "forbidden")
        self.assertEqual(verify.error.code, "forbidden")

    def test_tampered_json_and_markdown_are_detected_independently(self):
        report_id = self.create().data["report"]["report_id"]
        with sqlite3.connect(self.database) as connection:
            row = connection.execute("SELECT payload_json FROM risk_reports WHERE report_id = ?", (report_id,)).fetchone()
            payload = json.loads(row[0])
            payload["user_boundaries"]["max_loss"] = 99_999
            connection.execute(
                "UPDATE risk_reports SET payload_json = ? WHERE report_id = ?",
                (json.dumps(payload, ensure_ascii=False), report_id),
            )
        result = self.verify.invoke(self.owner, {"report_id": report_id})
        self.assertFalse(result.data["valid"])
        self.assertFalse(result.data["report_valid"])
        self.assertTrue(result.data["markdown_valid"])

        second_id = self.create("request-2").data["report"]["report_id"]
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "UPDATE risk_reports SET markdown = markdown || ? WHERE report_id = ?",
                ("\n篡改", second_id),
            )
        result = self.verify.invoke(self.owner, {"report_id": second_id})
        self.assertFalse(result.data["valid"])
        self.assertTrue(result.data["report_valid"])
        self.assertFalse(result.data["markdown_valid"])

    def test_repository_restart_recovers_full_report(self):
        created = self.create()
        report_id = created.data["report"]["report_id"]
        restarted = SQLiteRiskReportRepository(self.database)
        recovered = GetRiskReportTool(restarted).invoke(self.owner, {"report_id": report_id})
        self.assertTrue(recovered.success)
        self.assertEqual(recovered.data["report"]["report_id"], report_id)
        self.assertEqual(recovered.data["markdown"], created.data["markdown"])

    def test_snapshot_is_required(self):
        context = RuntimeContext(
            user_id="owner-001", entrypoint="unit-test",
            scenario=ProductScenario.CONSUMER_EDUCATION,
            as_of=self.owner.as_of,
        )
        response = self.build.invoke(context, report_arguments())
        self.assertFalse(response.success)
        self.assertIn("snapshot_id", response.error.message)


if __name__ == "__main__":
    unittest.main()

