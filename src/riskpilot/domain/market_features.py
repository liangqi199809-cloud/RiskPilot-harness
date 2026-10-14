"""Pure market-feature calculations used as risk-engine inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class RiskInputFeatures:
    price_date: str
    current_price: float
    atr_14: float
    key_support: float
    price_rows_used: int
    atr_period: int
    support_lookback: int


def calculate_atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> float:
    """Calculate ATR using the same deterministic rule as RiskPilot V1."""

    if len(highs) != len(lows) or len(lows) != len(closes):
        raise ValueError("high, low, and close series must have equal length")
    if period <= 0:
        raise ValueError("ATR period must be positive")
    if len(closes) < period + 1:
        return 0.0

    true_ranges = [
        max(
            highs[index] - lows[index],
            abs(highs[index] - closes[index - 1]),
            abs(lows[index] - closes[index - 1]),
        )
        for index in range(1, len(closes))
    ]
    recent = true_ranges[-period:]
    return sum(recent) / period


def find_key_support(closes: Sequence[float], lookback: int = 20) -> float:
    """Return the lowest close in the configured trailing window."""

    if lookback <= 0:
        raise ValueError("support lookback must be positive")
    if not closes:
        return 0.0
    return min(closes[-lookback:])


def extract_risk_input_features(
    prices: Sequence[Mapping[str, str]],
    atr_period: int = 14,
    support_lookback: int = 20,
) -> RiskInputFeatures:
    """Extract reproducible risk inputs from an already-visible price snapshot."""

    if len(prices) < atr_period + 1:
        raise ValueError(f"at least {atr_period + 1} visible price rows are required")
    dates = [row["日期"] for row in prices]
    if dates != sorted(set(dates)):
        raise ValueError("price dates must be unique and ascending")

    highs = [float(row["最高"]) for row in prices]
    lows = [float(row["最低"]) for row in prices]
    closes = [float(row["收盘"]) for row in prices]
    if any(not (0 < low <= close <= high) for low, close, high in zip(lows, closes, highs)):
        raise ValueError("price rows contain invalid high, low, or close values")

    return RiskInputFeatures(
        price_date=dates[-1],
        current_price=closes[-1],
        atr_14=calculate_atr(highs, lows, closes, atr_period),
        key_support=find_key_support(closes, support_lookback),
        price_rows_used=len(prices),
        atr_period=atr_period,
        support_lookback=support_lookback,
    )

