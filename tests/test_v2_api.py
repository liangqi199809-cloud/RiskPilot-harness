"""End-to-end tests for the V2 HTTP adapter and identity boundary."""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from riskpilot.api.app import create_v2_app
from riskpilot.api.auth import AuthenticatedIdentity, StaticBearerIdentityResolver
from riskpilot.harness.defaults import build_default_orchestrator


AS_OF = "2025-04-30T00:00:00Z"


class V2ApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "v2-api.sqlite3"
        self.runtime = build_default_orchestrator(self.database_path)
        identities = StaticBearerIdentityResolver(
            {
                "owner-token": AuthenticatedIdentity("owner-001"),
                "other-token": AuthenticatedIdentity("other-002"),
            }
        )
        self.client = TestClient(create_v2_app(self.runtime, identities))
        self.owner_headers = {"Authorization": "Bearer owner-token"}

    def tearDown(self):
        self.temporary.cleanup()

    def test_health_is_public_and_reports_identity_readiness(self):
        response = self.client.get("/api/v2/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertTrue(response.json()["identity_configured"])

    def test_protected_routes_require_a_valid_bearer_token(self):
        body = {"as_of": AS_OF, "limit": 10}
        missing = self.client.post("/api/v2/leaderboard/query", json=body)
        invalid = self.client.post(
            "/api/v2/leaderboard/query", json=body,
            headers={"Authorization": "Bearer wrong-token"},
        )
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(invalid.status_code, 401)
        self.assertNotIn("owner-token", invalid.text)

    def test_identity_resolver_repr_does_not_expose_tokens(self):
        resolver = StaticBearerIdentityResolver(
            {"top-secret-token": AuthenticatedIdentity("owner-001")}
        )
        self.assertNotIn("top-secret-token", repr(resolver))

    def test_no_identity_configuration_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            client = TestClient(create_v2_app(self.runtime))
        health = client.get("/api/v2/health")
        protected = client.post(
            "/api/v2/leaderboard/query",
            json={"as_of": AS_OF, "limit": 10},
            headers=self.owner_headers,
        )
        self.assertFalse(health.json()["identity_configured"])
        self.assertEqual(protected.status_code, 503)
        self.assertEqual(protected.json()["detail"]["code"], "identity_not_configured")

    def test_risk_budget_requires_snapshot_and_echoes_trace(self):
        body = {
            "as_of": AS_OF,
            "stock_code": "601318",
            "stock_name": "中国平安",
            "capital": 100000,
            "max_loss": 3000,
            "current_price": 50,
            "atr_14": 1.2,
            "key_support": 47,
            "board": "main",
        }
        denied = self.client.post("/api/v2/risk/budget", json=body, headers=self.owner_headers)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["error"]["code"], "policy_denied")

        body["snapshot_id"] = "601318-2025-04-30"
        headers = {**self.owner_headers, "X-Trace-ID": "trace-api-risk"}
        allowed = self.client.post("/api/v2/risk/budget", json=body, headers=headers)
        self.assertEqual(allowed.status_code, 200)
        self.assertTrue(allowed.json()["success"])
        self.assertEqual(allowed.headers["x-trace-id"], "trace-api-risk")
        self.assertEqual(allowed.json()["meta"]["trace_id"], "trace-api-risk")

        with sqlite3.connect(self.database_path) as connection:
            user_id, entrypoint = connection.execute(
                "SELECT user_id, entrypoint FROM tool_audit WHERE trace_id = ?",
                ("trace-api-risk",),
            ).fetchone()
        self.assertEqual(user_id, "owner-001")
        self.assertEqual(entrypoint, "v2_http_api")

    def test_replay_ownership_is_enforced_across_http_requests(self):
        created = self.client.post(
            "/api/v2/replay/cases",
            json={
                "as_of": AS_OF, "stock_code": "601318", "decision_mode": "monthly",
                "capital": 100000, "max_loss": 90000,
            },
            headers=self.owner_headers,
        )
        self.assertEqual(created.status_code, 200, created.text)
        experiment_id = created.json()["data"]["experiment_id"]
        resumed = self.client.post(
            "/api/v2/replay/session",
            json={"as_of": AS_OF, "experiment_id": experiment_id},
            headers=self.owner_headers,
        )
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(resumed.json()["data"]["step"], 0)
        preview = self.client.post(
            "/api/v2/replay/preview",
            json={
                "as_of": AS_OF, "experiment_id": experiment_id,
                "expected_step": 0, "target_value": 10000,
            },
            headers={"Authorization": "Bearer other-token"},
        )
        self.assertEqual(preview.status_code, 403)
        self.assertEqual(preview.json()["error"]["code"], "forbidden")

    def test_request_contract_rejects_unknown_fields_and_naive_time(self):
        unknown = self.client.post(
            "/api/v2/leaderboard/query",
            json={"as_of": AS_OF, "limit": 10, "admin": True},
            headers=self.owner_headers,
        )
        naive = self.client.post(
            "/api/v2/leaderboard/query",
            json={"as_of": "2025-04-30T00:00:00", "limit": 10},
            headers=self.owner_headers,
        )
        self.assertEqual(unknown.status_code, 422)
        self.assertEqual(naive.status_code, 422)

        invalid_trace = self.client.post(
            "/api/v2/leaderboard/query",
            json={"as_of": AS_OF, "limit": 10},
            headers={**self.owner_headers, "X-Trace-ID": "spaces are not allowed"},
        )
        self.assertEqual(invalid_trace.status_code, 422)

    def test_complete_report_http_flow_uses_server_snapshot_and_user_isolation(self):
        body = {
            "as_of": AS_OF, "snapshot_id": "601318-2025-04-30",
            "stock_code": "601318", "capital": 100000, "max_loss": 3000,
            "idempotency_key": "api-report-1",
        }
        created = self.client.post("/api/v2/reports", json=body, headers=self.owner_headers)
        self.assertEqual(created.status_code, 200, created.text)
        data = created.json()["data"]
        report = data["report"]
        report_id = report["report_id"]
        self.assertTrue(data["created"])
        self.assertEqual(report["snapshot_id"], body["snapshot_id"])
        self.assertEqual(report["stock"]["code"], "601318")
        self.assertEqual(report["perspectives"]["technical"]["status"], "unavailable")
        self.assertEqual(report["perspectives"]["fundamental"]["status"], "insufficient_evidence")
        chart = report["evidence"]["chart_data"]
        self.assertGreater(len(chart), 20)
        self.assertTrue(all(row["日期"] <= "2025-04-30" for row in chart))

        repeated = self.client.post("/api/v2/reports", json=body, headers=self.owner_headers)
        self.assertEqual(repeated.status_code, 200)
        self.assertFalse(repeated.json()["data"]["created"])
        self.assertEqual(repeated.json()["data"]["report"]["report_id"], report_id)

        query_body = {"as_of": AS_OF, "report_id": report_id}
        queried = self.client.post("/api/v2/reports/query", json=query_body, headers=self.owner_headers)
        checked = self.client.post("/api/v2/reports/integrity", json=query_body, headers=self.owner_headers)
        listed = self.client.post(
            "/api/v2/reports/list", json={"as_of": AS_OF, "limit": 10},
            headers=self.owner_headers,
        )
        self.assertEqual(queried.status_code, 200)
        self.assertIn("# RiskPilot 风险教育报告 V2", queried.json()["data"]["markdown"])
        self.assertTrue(checked.json()["data"]["valid"])
        self.assertEqual(listed.json()["data"]["count"], 1)
        self.assertEqual(listed.json()["data"]["reports"][0]["report_id"], report_id)

        forbidden = self.client.post(
            "/api/v2/reports/query", json=query_body,
            headers={"Authorization": "Bearer other-token"},
        )
        self.assertEqual(forbidden.status_code, 403)

        challenge = self.client.post(
            "/api/v2/replay/cases",
            json={
                "as_of": AS_OF, "stock_code": report["stock"]["code"],
                "decision_mode": "monthly", "capital": 100000, "max_loss": 90000,
            },
            headers=self.owner_headers,
        )
        self.assertEqual(challenge.status_code, 200)
        self.assertEqual(challenge.json()["data"]["stock_code"], report["stock"]["code"])

    def test_report_generation_rejects_client_snapshot_mismatch_and_unknown_fields(self):
        body = {
            "as_of": AS_OF, "snapshot_id": "601318-2025-05-01",
            "stock_code": "601318", "capital": 100000, "max_loss": 3000,
            "idempotency_key": "bad-snapshot",
        }
        mismatch = self.client.post("/api/v2/reports", json=body, headers=self.owner_headers)
        self.assertEqual(mismatch.status_code, 400)
        self.assertIn("does not match", mismatch.json()["error"]["message"])

        body["snapshot_id"] = "601318-2025-04-30"
        body["current_price"] = 1
        injected = self.client.post("/api/v2/reports", json=body, headers=self.owner_headers)
        self.assertEqual(injected.status_code, 422)


if __name__ == "__main__":
    unittest.main()
