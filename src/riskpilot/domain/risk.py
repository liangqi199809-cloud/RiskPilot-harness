"""Transport-neutral domain interface for the proven V1 risk rules.

The adapter intentionally delegates to the unchanged V1 deterministic engine.
Parity tests protect every returned field while callers migrate to this interface.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from backend.risk_engine import (
    FeeConfig,
    UserInput,
    calculate_position,
    run_stress_tests,
    validate_input,
)

RULE_VERSION = "risk-v1"


@dataclass(frozen=True, slots=True)
class RiskBudgetInput:
    stock_code: str
    stock_name: str
    capital: float
    max_loss: float
    current_price: float
    atr_14: float
    key_support: float
    board: str = "main"

    def to_legacy(self) -> UserInput:
        return UserInput(
            stock_code=self.stock_code,
            stock_name=self.stock_name,
            capital=self.capital,
            max_loss=self.max_loss,
            current_price=self.current_price,
            atr_14=self.atr_14,
            key_support=self.key_support,
            board=self.board,
        )


@dataclass(frozen=True, slots=True)
class RiskBudgetOutput:
    position: dict[str, Any]
    stress_tests: tuple[dict[str, Any], ...]


def calculate_risk_budget(
    request: RiskBudgetInput,
    config: FeeConfig | None = None,
) -> RiskBudgetOutput:
    """Calculate a risk budget without a web server, database, or model call."""

    legacy_input = request.to_legacy()
    errors = validate_input(legacy_input)
    if errors:
        raise ValueError("输入校验失败: " + "; ".join(errors))

    position = calculate_position(legacy_input, config)
    stress_tests = run_stress_tests(legacy_input, position, config)
    return RiskBudgetOutput(
        position=asdict(position),
        stress_tests=tuple(asdict(item) for item in stress_tests),
    )

