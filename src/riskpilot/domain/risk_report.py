"""Deterministic V2 risk-report assembly and integrity helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any, Mapping

from riskpilot.agents.report_perspectives import PerspectiveResult
from riskpilot.domain.reporting import DeterministicReportCore


RISK_REPORT_SCHEMA_VERSION = "risk-report-v2"
RISK_REPORT_RULE_VERSION = "risk-report-build-v1"


@dataclass(frozen=True, slots=True)
class BuiltRiskReport:
    payload: dict[str, Any]
    markdown: str


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def compute_report_hash(payload: Mapping[str, Any]) -> str:
    content = {key: value for key, value in payload.items() if key not in {"report_hash", "markdown_hash"}}
    return sha256_value(content)


def compute_markdown_hash(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def _perspective_payload(perspectives: Mapping[str, PerspectiveResult]) -> dict[str, Any]:
    expected = {"technical", "fundamental", "news"}
    if set(perspectives) != expected:
        raise ValueError("technical, fundamental, and news perspectives are required")
    result = {}
    for name in sorted(expected):
        value = perspectives[name]
        if value.perspective != name:
            raise ValueError(f"perspective key does not match payload: {name}")
        result[name] = asdict(value)
    return result


def build_risk_report(
    *, report_id: str, owner_id: str, snapshot_id: str, as_of: str,
    stock_code: str, stock_name: str, capital: float, max_loss: float,
    core: DeterministicReportCore, perspectives: Mapping[str, PerspectiveResult],
    evidence: Mapping[str, Any],
) -> BuiltRiskReport:
    """Assemble an immutable report from already-computed domain results."""
    if not all(value.strip() for value in (report_id, owner_id, snapshot_id, as_of, stock_code, stock_name)):
        raise ValueError("report identity, owner, snapshot, stock, and as_of are required")
    if len(stock_code) != 6 or not stock_code.isdigit():
        raise ValueError("stock_code must contain exactly six digits")
    if capital <= 0 or max_loss <= 0 or max_loss > capital:
        raise ValueError("capital and max_loss are invalid")
    payload: dict[str, Any] = {
        "report_id": report_id, "owner_id": owner_id,
        "snapshot_id": snapshot_id, "as_of": as_of,
        "schema_version": RISK_REPORT_SCHEMA_VERSION,
        "rule_version": RISK_REPORT_RULE_VERSION,
        "stock": {"code": stock_code, "name": stock_name},
        "user_boundaries": {"capital": capital, "max_loss": max_loss},
        "deterministic_core": asdict(core),
        "perspectives": _perspective_payload(perspectives),
        "evidence": dict(evidence),
        "disclosures": (
            "本报告用于金融风险教育和历史情景观察，不构成证券投资建议。",
            "确定性工具负责数字；模型解释不能覆盖或修改确定性结果。",
            "历史数据和静态价位触及次数不代表未来表现或策略胜率。",
        ),
    }
    payload["report_hash"] = compute_report_hash(payload)
    markdown = report_to_markdown(payload)
    payload["markdown_hash"] = compute_markdown_hash(markdown)
    return BuiltRiskReport(payload=payload, markdown=markdown)


def verify_risk_report(payload: Mapping[str, Any], markdown: str) -> dict[str, Any]:
    stored_report_hash = str(payload.get("report_hash", ""))
    stored_markdown_hash = str(payload.get("markdown_hash", ""))
    computed_report_hash = compute_report_hash(payload)
    computed_markdown_hash = compute_markdown_hash(markdown)
    report_valid = bool(stored_report_hash) and stored_report_hash == computed_report_hash
    markdown_valid = bool(stored_markdown_hash) and stored_markdown_hash == computed_markdown_hash
    return {
        "valid": report_valid and markdown_valid,
        "report_valid": report_valid, "markdown_valid": markdown_valid,
        "stored_report_hash": stored_report_hash,
        "computed_report_hash": computed_report_hash,
        "stored_markdown_hash": stored_markdown_hash,
        "computed_markdown_hash": computed_markdown_hash,
    }


def report_to_markdown(payload: Mapping[str, Any]) -> str:
    stock = payload["stock"]
    boundary = payload["user_boundaries"]
    core = payload["deterministic_core"]
    reference = core["scenario_reference"]
    trend = core["market_trend"]
    touch = core["historical_touch_test"]
    capital_flow = core["capital_flow"]
    lines = [
        "# RiskPilot 风险教育报告 V2", "",
        f"**股票：** {stock['name']}（{stock['code']}）",
        f"**历史截止时间：** {payload['as_of']}",
        f"**证据快照：** `{payload['snapshot_id']}`",
        f"**报告编号：** `{payload['report_id']}`", "",
        "## 用户风险边界", "",
        f"- 模拟本金：{boundary['capital']:,.2f} 元",
        f"- 标准情景最大损失预算：{boundary['max_loss']:,.2f} 元", "",
        "## 确定性历史观察", "",
        f"- 历史情景参考位：{reference['price']:.2f} 元（{reference['basis']}）",
        f"- 近期趋势：{trend['trend_label']}；{trend['basis']}",
        f"- 资金量价观察：{capital_flow['volume_price_status']}，OBV {capital_flow['obv_trend']}",
        f"- 风险保护参考位历史触及：{touch['stop_hit_count']} 次（{touch['stop_hit_rate']}%）",
        f"- 历史情景参考位触及：{touch['reference_hit_count']} 次（{touch['reference_hit_rate']}%）",
        f"- 方法说明：{touch['methodology_warning']}", "",
        "## 风险纪律检查", "",
    ]
    for check in core["discipline_checks"]:
        lines.append(f"- **{check['label']}** `{check['status']}`：{check['detail']}")
    lines.extend(("", "## 多视角解释", ""))
    for name, label in (("technical", "技术面"), ("fundamental", "基本面"), ("news", "信息面")):
        item = payload["perspectives"][name]
        lines.extend((f"### {label}", "", f"状态：`{item['status']}`", "", item["summary"], ""))
        if item["evidence_refs"]:
            lines.append("证据引用：" + "、".join(f"`{ref}`" for ref in item["evidence_refs"]))
            lines.append("")
    lines.extend(("## 重要说明", ""))
    lines.extend(f"- {item}" for item in payload["disclosures"])
    lines.extend(("", f"结构化报告哈希：`{payload['report_hash']}`", ""))
    return "\n".join(lines)

