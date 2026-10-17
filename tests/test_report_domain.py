"""R1 deterministic report-domain tests and V1 numeric parity checks."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from backtest import run_backtest
from capital_flow import calculate_capital_flow as calculate_legacy_capital_flow
from data_loader import extract_risk_engine_input, load_stock_snapshot
from risk_engine import UserInput, run_risk_engine
from riskpilot.domain.reporting import (
    REPORT_DOMAIN_SCHEMA_VERSION,
    REPORT_RULE_VERSION,
    build_deterministic_report_core,
    calculate_capital_flow,
    calculate_historical_touch_test,
    calculate_market_trend,
)


CASES = (
    ("601318", 100_000, 3_000),
    ("002594", 100_000, 3_000),
    ("600000", 100_000, 3_000),
    ("601318", 1_000, 100),
)


def load_case(code: str, capital: float, max_loss: float):
    snapshot = load_stock_snapshot(code)
    assert snapshot is not None
    info = extract_risk_engine_input(snapshot, code)
    output = run_risk_engine(UserInput(
        stock_code=code, stock_name=info["stock_name"], capital=capital,
        max_loss=max_loss, current_price=info["current_price"],
        atr_14=info["atr_14"], key_support=info["key_support"],
        board=info["board"],
    ))
    return info, output


class ReportDomainTests(unittest.TestCase):
    def test_capital_flow_numbers_match_v1_for_baseline_samples(self):
        for code, capital, max_loss in CASES:
            with self.subTest(code=code, capital=capital):
                info, _ = load_case(code, capital, max_loss)
                old = calculate_legacy_capital_flow(info["daily_data"])
                new = calculate_capital_flow(info["daily_data"])
                for field in (
                    "obv_current", "obv_ma5", "obv_trend", "flow_5d", "flow_20d",
                    "flow_5d_ratio", "flow_direction", "volume_price_status",
                    "vol_ma5", "vol_ma20", "vol_ratio", "volume_trend",
                ):
                    self.assertEqual(getattr(new, field), getattr(old, field), field)

    def test_touch_test_numbers_match_v1_for_baseline_samples(self):
        for code, capital, max_loss in CASES:
            with self.subTest(code=code, capital=capital):
                info, output = load_case(code, capital, max_loss)
                old = run_backtest(
                    info["daily_data"], info["current_price"],
                    output.position.stop_loss_price, info["target_price"],
                )
                new = calculate_historical_touch_test(
                    info["daily_data"], output.position.stop_loss_price,
                    info["target_price"],
                )
                self.assertEqual(new.lookback_days, old.lookback_days)
                self.assertEqual(new.stop_hit_count, old.stop_hit_count)
                self.assertEqual(new.reference_hit_count, old.target_hit_count)
                self.assertEqual(new.stop_hit_rate, old.stop_hit_rate)
                self.assertEqual(new.reference_hit_rate, old.target_hit_rate)
                self.assertEqual(new.max_drawdown, old.max_drawdown)
                self.assertEqual(new.max_drawdown_pct, old.max_drawdown_pct)
                self.assertEqual(new.avg_daily_range, old.avg_daily_range)
                self.assertEqual(new.volatility_level, old.volatility_level)
                self.assertIn("不是胜率", new.methodology_warning)

    def test_trend_matches_v1_rules(self):
        expected = {
            "601318": "sideways", "002594": "up", "600000": "sideways",
        }
        for code, trend in expected.items():
            info, _ = load_case(code, 100_000, 3_000)
            self.assertEqual(calculate_market_trend(info["daily_data"]).trend, trend)

    def test_report_core_is_versioned_repeatable_and_neutral(self):
        info, output = load_case("601318", 100_000, 3_000)
        arguments = dict(
            rows=info["daily_data"], capital=100_000, max_loss=3_000,
            current_price=info["current_price"],
            stop_price=output.position.stop_loss_price,
            shares=output.position.final_shares,
            standard_loss=output.position.standard_loss,
        )
        first = build_deterministic_report_core(**arguments)
        second = build_deterministic_report_core(**arguments)
        self.assertEqual(first, second)
        self.assertEqual(first.schema_version, REPORT_DOMAIN_SCHEMA_VERSION)
        self.assertEqual(first.rule_version, REPORT_RULE_VERSION)
        self.assertEqual(first.scenario_reference.label, "历史情景参考位")
        rendered = str(asdict(first))
        for prohibited in ("建议买入", "建议卖出", "目标价", "可以买入"):
            self.assertNotIn(prohibited, rendered)
        self.assertEqual(
            {item.check_id for item in first.discipline_checks},
            {"loss_budget", "minimum_lot", "position_concentration",
             "scenario_asymmetry", "execution_limits"},
        )

    def test_insufficient_evidence_is_explicit(self):
        rows = [
            {"high": 11 + i / 10, "low": 9 + i / 10,
             "close": 10 + i / 10, "volume": 1000 + i}
            for i in range(9)
        ]
        self.assertEqual(calculate_capital_flow(rows).evidence_status, "insufficient_evidence")
        self.assertEqual(
            calculate_historical_touch_test(rows, 9, 12).evidence_status,
            "insufficient_evidence",
        )
        self.assertEqual(calculate_market_trend(rows).evidence_status, "insufficient_evidence")

    def test_invalid_rows_are_rejected(self):
        with self.assertRaises(ValueError):
            calculate_market_trend([{"high": 9, "low": 10, "close": 11, "volume": 1}])


if __name__ == "__main__":
    unittest.main()
