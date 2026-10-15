"""Explanation boundary that treats deterministic tool output as authoritative."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from riskpilot.agents.model_gateway import ModelGateway, ModelRequest, ModelResult
from riskpilot.harness.responses import ToolResponse

EXPLANATION_PROMPT_VERSION = "tool-explanation-v1"
EXPLANATION_INSTRUCTIONS = """你是金融风险教育讲解员。只能解释给定的确定性工具结果。
不得修改、补造或重新计算任何数字；不得给出收益承诺、实盘买卖指令或工具结果之外的事实。
清楚区分可核验结果、解释和不确定性。若信息不足，明确说明不足。"""


@dataclass(frozen=True, slots=True)
class ToolResultExplainer:
    gateway: ModelGateway

    def explain(self, response: ToolResponse[Any], audience: str = "投资新手") -> ModelResult:
        if not response.success:
            raise ValueError("failed tool response cannot be explained")
        evidence = json.dumps(
            response.to_dict(), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False, default=str,
        )
        request = ModelRequest(
            task="explain_tool_result",
            instructions=EXPLANATION_INSTRUCTIONS,
            input_text=f"受众：{audience}\n权威工具结果（JSON）：{evidence}",
            prompt_version=EXPLANATION_PROMPT_VERSION,
        )
        return self.gateway.generate(request)

