"""R2 evidence and failure-boundary tests for report interpreters."""

from __future__ import annotations

import json
import unittest

from riskpilot.agents import (
    FundamentalInterpreter, NewsInterpreter, OfflineModelGateway,
    PerspectiveEvidence, TechnicalInterpreter,
)
from riskpilot.agents.model_gateway import ModelResult


class CapturingGateway:
    def __init__(self, payload=None):
        self.requests = []
        self.payload = payload or {
            "summary": "历史样本显示短期走势震荡。",
            "observations": ["均线方向不一致。"],
            "risks": ["波动可能扩大。"],
            "invalidation_conditions": ["证据窗口更新后需重新解释。"],
            "uncertainties": ["历史指标不预测未来。"],
            "evidence_refs": ["price-1"],
        }

    def generate(self, request):
        self.requests.append(request)
        return ModelResult(
            success=True, text=json.dumps(self.payload, ensure_ascii=False),
            mode="live", provider="test", model="test-model",
            prompt_version=request.prompt_version, response_id="response-1",
        )


def evidence(evidence_id="price-1", evidence_type="price_snapshot"):
    return PerspectiveEvidence(
        evidence_id=evidence_id, evidence_type=evidence_type,
        source="verified-snapshot", as_of="2025-08-31T15:00:00+08:00",
        facts={"trend": "sideways", "ma5": 59.79, "ma20": 59.24},
    )


class ReportPerspectiveTests(unittest.TestCase):
    def test_technical_interpreter_returns_versioned_structured_result(self):
        gateway = CapturingGateway()
        result = TechnicalInterpreter(gateway).interpret([evidence()])
        self.assertEqual(result.status, "available")
        self.assertEqual(result.prompt_version, "report-technical-v1")
        self.assertEqual(result.evidence_refs, ("price-1",))
        self.assertEqual(gateway.requests[0].task, "interpret_technical_evidence")
        self.assertIn('"evidence_id":"price-1"', gateway.requests[0].input_text)
        self.assertIn("不得修改", gateway.requests[0].instructions)

    def test_each_interpreter_accepts_only_its_evidence_types(self):
        fundamental_gateway = CapturingGateway({
            **CapturingGateway().payload, "evidence_refs": ["financial-1"],
        })
        fundamental = FundamentalInterpreter(fundamental_gateway).interpret([
            evidence("financial-1", "financial_statement")
        ])
        self.assertEqual(fundamental.status, "available")

        news_gateway = CapturingGateway({
            **CapturingGateway().payload, "evidence_refs": ["announcement-1"],
        })
        news = NewsInterpreter(news_gateway).interpret([
            evidence("announcement-1", "announcement")
        ])
        self.assertEqual(news.status, "available")

        wrong_gateway = CapturingGateway()
        missing = FundamentalInterpreter(wrong_gateway).interpret([evidence()])
        self.assertEqual(missing.status, "insufficient_evidence")
        self.assertEqual(missing.error_code, "insufficient_evidence")
        self.assertEqual(wrong_gateway.requests, [])

    def test_offline_model_is_explicit_and_keeps_result_empty(self):
        result = TechnicalInterpreter(OfflineModelGateway()).interpret([evidence()])
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.error_code, "model_offline")
        self.assertEqual(result.observations, ())
        self.assertIn("不可用", result.summary)

    def test_unknown_evidence_reference_is_rejected(self):
        gateway = CapturingGateway({
            **CapturingGateway().payload, "evidence_refs": ["invented-source"],
        })
        result = TechnicalInterpreter(gateway).interpret([evidence()])
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.error_code, "invalid_model_output")
        self.assertEqual(result.evidence_refs, ())

    def test_non_json_and_trading_language_are_rejected(self):
        class NonJsonGateway(CapturingGateway):
            def generate(self, request):
                return ModelResult(
                    True, "not json", "live", "test", "model",
                    request.prompt_version,
                )

        self.assertEqual(
            TechnicalInterpreter(NonJsonGateway()).interpret([evidence()]).error_code,
            "invalid_model_output",
        )
        gateway = CapturingGateway({
            **CapturingGateway().payload,
            "summary": "可以买入，目标价未知。",
        })
        result = TechnicalInterpreter(gateway).interpret([evidence()])
        self.assertEqual(result.error_code, "invalid_model_output")

    def test_evidence_requires_identity_time_source_and_facts(self):
        with self.assertRaises(ValueError):
            PerspectiveEvidence("", "price_snapshot", "source", "2025-01-01", {"x": 1})
        with self.assertRaises(ValueError):
            PerspectiveEvidence("id", "price_snapshot", "source", "2025-01-01", {})


if __name__ == "__main__":
    unittest.main()
