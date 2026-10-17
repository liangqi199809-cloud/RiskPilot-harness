"""Evidence-bound, structured report perspective interpreters.

The interpreters never calculate report numbers. They receive already-visible
evidence, ask an injected model gateway for JSON explanations, and validate that
the response cites only supplied evidence identifiers. Missing evidence and
model failure are explicit states rather than fabricated fallback prose.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, Sequence

from riskpilot.agents.model_gateway import ModelGateway, ModelRequest


TECHNICAL_PROMPT_VERSION = "report-technical-v1"
FUNDAMENTAL_PROMPT_VERSION = "report-fundamental-v1"
NEWS_PROMPT_VERSION = "report-news-v1"

_PROHIBITED_PHRASES = ("建议买入", "建议卖出", "可以买入", "应该买入", "目标价")
_BASE_INSTRUCTIONS = """你是金融风险教育产品的证据解释器。只可使用输入 JSON 中的证据。
不得修改或重新计算确定性数字，不得引入常识性公司事实，不得预测收益，不得给出实盘买卖指令。
只输出一个 JSON 对象，不要 Markdown，不要思维过程。字段必须为：
summary（字符串）、observations（字符串数组）、risks（字符串数组）、
invalidation_conditions（字符串数组）、uncertainties（字符串数组）、evidence_refs（字符串数组）。
evidence_refs 只能填写输入中出现的 evidence_id。每个实质判断都应能由所引证证据支持。"""


@dataclass(frozen=True, slots=True)
class PerspectiveEvidence:
    evidence_id: str
    evidence_type: str
    source: str
    as_of: str
    facts: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not all((self.evidence_id.strip(), self.evidence_type.strip(), self.source.strip(), self.as_of.strip())):
            raise ValueError("evidence identity, type, source, and as_of are required")
        if not self.facts:
            raise ValueError("evidence facts must not be empty")


@dataclass(frozen=True, slots=True)
class PerspectiveResult:
    perspective: str
    status: str
    summary: str
    observations: tuple[str, ...]
    risks: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    uncertainties: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    prompt_version: str
    provider: str | None = None
    model: str | None = None
    response_id: str | None = None
    error_code: str | None = None


class _PerspectiveInterpreter:
    perspective: str
    prompt_version: str
    accepted_evidence_types: frozenset[str]

    def __init__(self, gateway: ModelGateway):
        self.gateway = gateway

    def interpret(self, evidence: Sequence[PerspectiveEvidence]) -> PerspectiveResult:
        relevant = tuple(item for item in evidence if item.evidence_type in self.accepted_evidence_types)
        if not relevant:
            return self._unavailable(
                "insufficient_evidence",
                "当前快照没有足够的可追溯证据，不能形成该视角结论。",
            )
        input_text = json.dumps(
            {
                "perspective": self.perspective,
                "evidence": [
                    {
                        "evidence_id": item.evidence_id,
                        "evidence_type": item.evidence_type,
                        "source": item.source,
                        "as_of": item.as_of,
                        "facts": item.facts,
                    }
                    for item in relevant
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        )
        model_result = self.gateway.generate(ModelRequest(
            task=f"interpret_{self.perspective}_evidence",
            instructions=_BASE_INSTRUCTIONS + "\n" + self._perspective_instructions(),
            input_text=input_text,
            prompt_version=self.prompt_version,
            max_output_tokens=1000,
        ))
        if not model_result.success:
            return self._unavailable(
                model_result.error_code or "model_error", model_result.text,
                provider=model_result.provider, model=model_result.model,
                response_id=model_result.response_id,
            )
        try:
            payload = json.loads(model_result.text)
            parsed = self._validate_payload(payload, {item.evidence_id for item in relevant})
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return self._unavailable(
                "invalid_model_output", f"模型输出未通过结构或证据引用校验：{exc}",
                provider=model_result.provider, model=model_result.model,
                response_id=model_result.response_id,
            )
        return PerspectiveResult(
            perspective=self.perspective, status="available",
            prompt_version=self.prompt_version, provider=model_result.provider,
            model=model_result.model, response_id=model_result.response_id,
            **parsed,
        )

    def _validate_payload(self, payload: Any, allowed_refs: set[str]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("top-level value must be an object")
        required = {
            "summary", "observations", "risks", "invalidation_conditions",
            "uncertainties", "evidence_refs",
        }
        if set(payload) != required:
            raise ValueError("output fields do not match the versioned contract")
        summary = payload["summary"]
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("summary must be a non-empty string")
        arrays: dict[str, tuple[str, ...]] = {}
        for field in required - {"summary"}:
            values = payload[field]
            if not isinstance(values, list) or len(values) > 12:
                raise ValueError(f"{field} must be an array with at most 12 items")
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError(f"{field} must contain non-empty strings")
            arrays[field] = tuple(values)
        if not arrays["evidence_refs"]:
            raise ValueError("at least one evidence reference is required")
        unknown = set(arrays["evidence_refs"]) - allowed_refs
        if unknown:
            raise ValueError(f"unknown evidence references: {sorted(unknown)}")
        combined = " ".join((summary, *arrays["observations"], *arrays["risks"]))
        if any(phrase in combined for phrase in _PROHIBITED_PHRASES):
            raise ValueError("output contains public-product prohibited trading language")
        return {"summary": summary.strip(), **arrays}

    def _unavailable(
        self, error_code: str, message: str, *, provider: str | None = None,
        model: str | None = None, response_id: str | None = None,
    ) -> PerspectiveResult:
        status = "insufficient_evidence" if error_code == "insufficient_evidence" else "unavailable"
        return PerspectiveResult(
            perspective=self.perspective, status=status, summary=message,
            observations=(), risks=(), invalidation_conditions=(),
            uncertainties=(message,), evidence_refs=(),
            prompt_version=self.prompt_version, provider=provider, model=model,
            response_id=response_id, error_code=error_code,
        )

    def _perspective_instructions(self) -> str:
        raise NotImplementedError


class TechnicalInterpreter(_PerspectiveInterpreter):
    perspective = "technical"
    prompt_version = TECHNICAL_PROMPT_VERSION
    accepted_evidence_types = frozenset({"price_snapshot", "technical_indicators"})

    def _perspective_instructions(self) -> str:
        return "只解释历史价格、成交量、波动和趋势事实；不得输出未来点位预测。"


class FundamentalInterpreter(_PerspectiveInterpreter):
    perspective = "fundamental"
    prompt_version = FUNDAMENTAL_PROMPT_VERSION
    accepted_evidence_types = frozenset({"financial_statement", "fundamental_facts"})

    def _perspective_instructions(self) -> str:
        return "只解释已提供财务字段及其报告期和口径；缺失指标不得估算或补写。"


class NewsInterpreter(_PerspectiveInterpreter):
    perspective = "news"
    prompt_version = NEWS_PROMPT_VERSION
    accepted_evidence_types = frozenset({"official_document", "announcement"})

    def _perspective_instructions(self) -> str:
        return "只解释已提供公告或官方原文；仅有标题时不得推断正文、影响方向或市场情绪。"

