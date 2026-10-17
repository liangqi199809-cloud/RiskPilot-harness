"""Deterministic report-domain calculations.

This module deliberately has no HTTP, database, model, or clock dependency.  A
caller that supplies the same visible OHLCV rows, risk result, and rule version
receives the same structure and numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


REPORT_DOMAIN_SCHEMA_VERSION = "report-domain-v1"
REPORT_RULE_VERSION = "report-rules-v1"


@dataclass(frozen=True, slots=True)
class PriceBar:
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True, slots=True)
class CapitalFlowMetrics:
    evidence_status: str
    obv_current: float
    obv_ma5: float
    obv_trend: str
    flow_5d: float
    flow_20d: float
    flow_5d_ratio: float
    flow_direction: str
    volume_price_status: str
    vol_ma5: float
    vol_ma20: float
    vol_ratio: float
    volume_trend: str
    turnover_level: str
    bullish_signals: tuple[str, ...]
    bearish_signals: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HistoricalTouchTest:
    evidence_status: str
    lookback_days: int
    stop_hit_count: int
    reference_hit_count: int
    stop_hit_rate: float
    reference_hit_rate: float
    max_drawdown: float
    max_drawdown_pct: float
    avg_daily_range: float
    volatility_level: str
    interpretation: str
    methodology_warning: str


@dataclass(frozen=True, slots=True)
class MarketTrend:
    evidence_status: str
    trend: str
    trend_label: str
    ma5: float
    ma20: float
    change_20d: float
    basis: str
    observation: str


@dataclass(frozen=True, slots=True)
class HistoricalScenarioReference:
    label: str
    price: float
    basis: str
    lookback_days: int
    is_projection: bool = False


@dataclass(frozen=True, slots=True)
class DisciplineCheck:
    check_id: str
    label: str
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class DeterministicReportCore:
    schema_version: str
    rule_version: str
    source_rows: int
    capital_flow: CapitalFlowMetrics
    historical_touch_test: HistoricalTouchTest
    market_trend: MarketTrend
    scenario_reference: HistoricalScenarioReference
    discipline_checks: tuple[DisciplineCheck, ...]


def _number(row: Mapping[str, Any], *keys: str) -> float:
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            try:
                return float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"price field {key!r} must be numeric") from exc
    return 0.0


def normalize_price_bars(rows: Sequence[Mapping[str, Any]]) -> tuple[PriceBar, ...]:
    """Validate and normalize the English/Chinese snapshot field variants."""

    bars = []
    for index, row in enumerate(rows):
        high = _number(row, "high", "最高")
        low = _number(row, "low", "最低")
        close = _number(row, "close", "c", "收盘")
        volume = _number(row, "volume", "vol", "amount", "成交量")
        if not (0 < low <= close <= high):
            raise ValueError(f"price row {index} has invalid high, low, or close")
        if volume < 0:
            raise ValueError(f"price row {index} has negative volume")
        bars.append(PriceBar(high=high, low=low, close=close, volume=volume))
    return tuple(bars)


def calculate_capital_flow(rows: Sequence[Mapping[str, Any]]) -> CapitalFlowMetrics:
    """Calculate reproducible OHLCV-derived observations (not real fund flows)."""

    bars = normalize_price_bars(rows)
    if len(bars) < 20:
        return CapitalFlowMetrics(
            evidence_status="insufficient_evidence", obv_current=0, obv_ma5=0,
            obv_trend="数据不足", flow_5d=0, flow_20d=0, flow_5d_ratio=0,
            flow_direction="数据不足", volume_price_status="数据不足",
            vol_ma5=0, vol_ma20=0, vol_ratio=0, volume_trend="数据不足",
            turnover_level="数据不足", bullish_signals=(), bearish_signals=(),
        )

    data = bars[-60:]
    closes = [bar.close for bar in data]
    volumes = [bar.volume for bar in data]
    obv_values: list[float] = []
    obv = 0.0
    for index, volume in enumerate(volumes):
        if index == 0:
            obv = volume
        elif closes[index] > closes[index - 1]:
            obv += volume
        elif closes[index] < closes[index - 1]:
            obv -= volume
        obv_values.append(obv)

    obv_current = obv_values[-1]
    obv_ma5 = sum(obv_values[-5:]) / 5
    obv_ma20 = sum(obv_values[-20:]) / 20
    if obv_current > obv_ma5 > obv_ma20:
        obv_trend = "持续上升"
    elif obv_current < obv_ma5 < obv_ma20:
        obv_trend = "持续下降"
    elif obv_current > obv_ma20:
        obv_trend = "震荡偏强"
    else:
        obv_trend = "震荡偏弱"

    def flow(days: int) -> tuple[float, float]:
        signed = 0.0
        total = 0.0
        for index in range(max(1, len(data) - days), len(data)):
            total += volumes[index]
            if closes[index] > closes[index - 1]:
                signed += volumes[index]
            elif closes[index] < closes[index - 1]:
                signed -= volumes[index]
        return signed, total

    flow_5d, total_5d = flow(5)
    flow_20d, _ = flow(20)
    if flow_5d > 0 and flow_20d > 0:
        flow_direction = "持续净流入"
    elif flow_5d < 0 and flow_20d < 0:
        flow_direction = "持续净流出"
    elif flow_5d > 0:
        flow_direction = "短期流入、中期流出"
    else:
        flow_direction = "短期流出、中期流入"

    price_change_5d = (closes[-1] / closes[-6] - 1) * 100
    vol_ma5 = sum(volumes[-5:]) / 5
    vol_ma20 = sum(volumes[-20:]) / 20
    vol_change = (vol_ma5 / vol_ma20 - 1) * 100 if vol_ma20 > 0 else 0
    if price_change_5d > 1 and vol_change > 10:
        volume_price_status = "放量上涨"
    elif price_change_5d > 1 and vol_change < -10:
        volume_price_status = "缩量上涨"
    elif price_change_5d < -1 and vol_change > 10:
        volume_price_status = "放量下跌"
    elif price_change_5d < -1 and vol_change < -10:
        volume_price_status = "缩量下跌"
    else:
        volume_price_status = "量价平稳"

    vol_ratio = vol_ma5 / vol_ma20 if vol_ma20 > 0 else 1
    volume_trend = (
        "明显放大" if vol_ratio > 1.3 else
        "温和放大" if vol_ratio > 1.1 else
        "明显萎缩" if vol_ratio < 0.7 else
        "温和萎缩" if vol_ratio < 0.9 else "平稳"
    )
    sorted_volumes = sorted(volumes)
    percentile = sum(value <= vol_ma5 for value in sorted_volumes) / len(sorted_volumes) * 100
    turnover_level = "高" if percentile >= 70 else "中等" if percentile >= 40 else "低"

    bullish: list[str] = []
    bearish: list[str] = []
    (bullish if "上升" in obv_trend or "偏强" in obv_trend else bearish).append(
        f"OBV{obv_trend}"
    )
    (bullish if flow_5d > 0 else bearish).append(
        f"近5日成交量方向估算{'为正' if flow_5d > 0 else '为负'}"
    )
    if volume_price_status in ("放量上涨", "缩量下跌"):
        bullish.append(volume_price_status)
    elif volume_price_status in ("缩量上涨", "放量下跌"):
        bearish.append(volume_price_status)

    return CapitalFlowMetrics(
        evidence_status="available", obv_current=round(obv_current, 0),
        obv_ma5=round(obv_ma5, 0), obv_trend=obv_trend,
        flow_5d=round(flow_5d, 0), flow_20d=round(flow_20d, 0),
        flow_5d_ratio=round(flow_5d / total_5d * 100, 2) if total_5d > 0 else 0,
        flow_direction=flow_direction, volume_price_status=volume_price_status,
        vol_ma5=round(vol_ma5, 0), vol_ma20=round(vol_ma20, 0),
        vol_ratio=round(vol_ratio, 2), volume_trend=volume_trend,
        turnover_level=turnover_level, bullish_signals=tuple(bullish),
        bearish_signals=tuple(bearish),
    )


def calculate_historical_touch_test(
    rows: Sequence[Mapping[str, Any]], stop_price: float, reference_price: float,
    lookback: int = 120,
) -> HistoricalTouchTest:
    """Describe static historical price-level touches; this is not a backtest."""

    if stop_price <= 0 or reference_price <= 0 or lookback <= 0:
        raise ValueError("prices and lookback must be positive")
    bars = normalize_price_bars(rows)
    warning = "仅统计静态价位的历史触及次数；不模拟先后顺序，不是胜率或未来预测。"
    if len(bars) < 10:
        return HistoricalTouchTest(
            evidence_status="insufficient_evidence", lookback_days=0,
            stop_hit_count=0, reference_hit_count=0, stop_hit_rate=0,
            reference_hit_rate=0, max_drawdown=0, max_drawdown_pct=0,
            avg_daily_range=0, volatility_level="数据不足",
            interpretation="历史数据不足，无法统计价格触及情况。",
            methodology_warning=warning,
        )
    data = bars[-lookback:]
    stop_hits = sum(bar.low <= stop_price for bar in data)
    reference_hits = sum(bar.high >= reference_price for bar in data)
    peak = data[0].high
    max_drawdown = max_drawdown_pct = 0.0
    for bar in data:
        peak = max(peak, bar.high)
        drawdown = peak - bar.low
        if drawdown > max_drawdown:
            max_drawdown = drawdown
            max_drawdown_pct = drawdown / peak * 100 if peak > 0 else 0
    ranges = [(bar.high - bar.low) / bar.low * 100 for bar in data]
    avg_range = sum(ranges) / len(ranges)
    volatility = (
        "高波动" if avg_range >= 4 else "中高波动" if avg_range >= 2.5
        else "中等波动" if avg_range >= 1.5 else "低波动"
    )
    n = len(data)
    stop_rate = stop_hits / n * 100
    reference_rate = reference_hits / n * 100
    interpretation = (
        f"过去{n}个交易日，风险保护参考位触及{stop_hits}次，"
        f"历史情景参考位触及{reference_hits}次。"
    )
    return HistoricalTouchTest(
        evidence_status="available", lookback_days=n,
        stop_hit_count=stop_hits, reference_hit_count=reference_hits,
        stop_hit_rate=round(stop_rate, 1), reference_hit_rate=round(reference_rate, 1),
        max_drawdown=round(max_drawdown, 2),
        max_drawdown_pct=round(max_drawdown_pct, 2),
        avg_daily_range=round(avg_range, 2), volatility_level=volatility,
        interpretation=interpretation, methodology_warning=warning,
    )


def calculate_market_trend(rows: Sequence[Mapping[str, Any]]) -> MarketTrend:
    bars = normalize_price_bars(rows)
    if len(bars) < 20:
        return MarketTrend(
            evidence_status="insufficient_evidence", trend="unknown",
            trend_label="数据不足", ma5=0, ma20=0, change_20d=0, basis="",
            observation="不足20个交易日，不能形成近期趋势观察。",
        )
    closes = [bar.close for bar in bars]
    ma5 = sum(closes[-5:]) / 5
    ma20 = sum(closes[-20:]) / 20
    change = (closes[-1] - closes[-20]) / closes[-20] * 100
    if ma5 > ma20 * 1.01 and change > 3:
        trend, label = "up", "近期上涨趋势"
        basis = f"MA5({ma5:.2f}) > MA20({ma20:.2f})，近20日涨{change:.1f}%"
    elif ma5 < ma20 * 0.99 and change < -3:
        trend, label = "down", "近期下跌趋势"
        basis = f"MA5({ma5:.2f}) < MA20({ma20:.2f})，近20日跌{abs(change):.1f}%"
    else:
        trend, label = "sideways", "近期震荡"
        basis = f"MA5({ma5:.2f})≈MA20({ma20:.2f})，近20日涨跌{change:+.1f}%"
    observations = {
        "up": "历史样本显示短期动能偏强；这不是继续上涨的预测。",
        "down": "历史样本显示短期动能偏弱；应重点检查风险预算和失效条件。",
        "sideways": "历史样本方向不明确；应避免把震荡误读为确定趋势。",
    }
    return MarketTrend(
        evidence_status="available", trend=trend, trend_label=label,
        ma5=round(ma5, 2), ma20=round(ma20, 2), change_20d=round(change, 2),
        basis=basis, observation=observations[trend],
    )


def calculate_scenario_reference(
    rows: Sequence[Mapping[str, Any]], current_price: float, lookback: int = 20,
) -> HistoricalScenarioReference:
    """Return an observed/fallback scenario level without calling it a target."""

    if current_price <= 0 or lookback <= 0:
        raise ValueError("current price and lookback must be positive")
    bars = normalize_price_bars(rows)
    if not bars:
        raise ValueError("at least one price row is required")
    observed_high = max(bar.high for bar in bars[-lookback:])
    price = max(observed_high, current_price * 1.03)
    used_fallback = observed_high <= current_price
    basis = (
        "当前可见窗口高点不高于参考价，使用当前价上方3%的规则化情景位"
        if used_fallback else f"最近{min(lookback, len(bars))}个交易日可见最高价"
    )
    return HistoricalScenarioReference(
        label="历史情景参考位", price=round(price, 2), basis=basis,
        lookback_days=min(lookback, len(bars)), is_projection=used_fallback,
    )


def build_risk_discipline_checks(
    *, capital: float, max_loss: float, current_price: float, stop_price: float,
    shares: int, standard_loss: float, scenario_reference_price: float,
) -> tuple[DisciplineCheck, ...]:
    """Build neutral review checks, never buy/sell instructions."""

    if capital <= 0 or max_loss <= 0 or current_price <= 0 or stop_price <= 0:
        raise ValueError("capital, loss budget, and prices must be positive")
    if shares < 0 or standard_loss < 0:
        raise ValueError("shares and standard loss cannot be negative")
    position_value = shares * current_price
    position_rate = position_value / capital * 100
    loss_status = "pass" if standard_loss <= max_loss and shares >= 100 else "blocked"
    rr = ((scenario_reference_price - current_price) / (current_price - stop_price)
          if current_price > stop_price else 0)
    return (
        DisciplineCheck(
            "loss_budget", "标准情景是否在损失预算内", loss_status,
            f"标准情景损失{standard_loss:.2f}元；用户预算{max_loss:.2f}元。",
        ),
        DisciplineCheck(
            "minimum_lot", "是否满足最小模拟仓位", "pass" if shares >= 100 else "blocked",
            f"规则计算得到{shares}股；不足100股时不形成模拟仓位。",
        ),
        DisciplineCheck(
            "position_concentration", "单一标的资金集中度",
            "review" if position_rate > 50 else "pass",
            f"模拟仓位占本金{position_rate:.2f}%。",
        ),
        DisciplineCheck(
            "scenario_asymmetry", "历史情景空间与保护距离",
            "review" if rr < 1 else "pass",
            f"按历史情景参考位测算的空间/保护距离比为1:{rr:.2f}；仅用于风险教育。",
        ),
        DisciplineCheck(
            "execution_limits", "极端执行风险已阅读", "review",
            "跳空、跌停、停牌和流动性不足可能使实际损失超过标准情景。",
        ),
    )


def build_deterministic_report_core(
    rows: Sequence[Mapping[str, Any]], *, capital: float, max_loss: float,
    current_price: float, stop_price: float, shares: int, standard_loss: float,
) -> DeterministicReportCore:
    reference = calculate_scenario_reference(rows, current_price)
    return DeterministicReportCore(
        schema_version=REPORT_DOMAIN_SCHEMA_VERSION,
        rule_version=REPORT_RULE_VERSION,
        source_rows=len(rows),
        capital_flow=calculate_capital_flow(rows),
        historical_touch_test=calculate_historical_touch_test(
            rows, stop_price, reference.price
        ),
        market_trend=calculate_market_trend(rows),
        scenario_reference=reference,
        discipline_checks=build_risk_discipline_checks(
            capital=capital, max_loss=max_loss, current_price=current_price,
            stop_price=stop_price, shares=shares, standard_loss=standard_loss,
            scenario_reference_price=reference.price,
        ),
    )
