"""Focused V6 implementation verification."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from functions.data_integrity import build_data_integrity_report, data_verified, save_data_integrity_artifacts
from functions.event_statistics import (
    attach_event_labels,
    beta_binomial_win_rate,
    build_event_density_report,
    build_independent_events,
    mature_events,
    robust_payoff_ratio,
)
from functions.strategy_admission import build_strategy_admission_report


def main():
    _verify_bayesian_lower_bound()
    _verify_robust_payoff()
    events = _verify_events_and_labels()
    _verify_binary_admission(events)
    _verify_data_gate()
    print("V6 core verification passed.")


def _verify_bayesian_lower_bound():
    cold = beta_binomial_win_rate(0, 0)
    assert cold.mean == 0.5
    assert cold.lower_bound < cold.mean
    observed = beta_binomial_win_rate(70, 30)
    assert 0.5 < observed.lower_bound < observed.mean < 0.8
    print("[PASS] Bayesian lower confidence bound")


def _verify_robust_payoff():
    result = robust_payoff_ratio(pd.Series([0.02, 0.03, 0.04, -0.01, -0.02, -2.0]))
    assert 1.0 <= result["payoff_ratio"] <= 3.0
    assert result["tail_loss_95"] > 0.0
    print("[PASS] robust payoff clipping and diagnostics")


def _verify_events_and_labels():
    signals = pd.DataFrame(
        [
            ("macd_cross", "sh600000", "long", "2024-01-02 15:30", "2024-01-03 09:30", "2024-01-10"),
            ("macd_cross", "sh600000", "long", "2024-01-03 15:30", "2024-01-04 09:30", "2024-01-11"),
            ("macd_cross", "sh600000", "long", "2024-01-10 15:30", "2024-01-11 09:30", "2024-01-18"),
        ],
        columns=["strategy_id", "symbol", "direction", "signal_timestamp", "tradeable_timestamp", "reference_date"],
    )
    signals["return_horizon_days"] = 5
    events = build_independent_events(signals, cooldown_days={"macd_cross": 5})
    assert events["is_independent_event"].sum() == 2
    mature = mature_events(events, "2024-01-20")
    assert len(mature) == 2
    dates = pd.bdate_range("2024-01-03", "2024-01-18")
    prices = pd.DataFrame(
        {
            "symbol": "sh600000",
            "date": dates,
            "open": 10.0,
            "high": 10.5,
            "low": 9.8,
            "close": [10.0 + index * 0.05 for index in range(len(dates))],
        }
    )
    labeled = attach_event_labels(mature, prices, round_trip_cost_rate=0.001)
    assert {"classification_label", "regression_label", "ranking_label", "adverse_move", "favorable_move"}.issubset(labeled)
    density = build_event_density_report(events)
    assert density["independent_events"].sum() == 2
    print("[PASS] independent events, maturity, labels, and density")
    return density


def _verify_binary_admission(density):
    metrics = pd.DataFrame(
        [
            {
                "strategy_id": "macd_cross",
                "net_total_return": 0.10,
                "information_ratio": 0.5,
                "max_drawdown": -0.10,
                "failed_order_ratio": 0.01,
                "parameter_stability_passed": True,
                "calibration_passed": True,
                "capacity_passed": True,
            }
        ]
    )
    report = build_strategy_admission_report(metrics, event_density=density)
    assert set(report["admission_status"]).issubset({"PASS", "FAIL"})
    assert (report["admission_status"] == "FAIL").all()
    assert not report["formal_weight_enabled"].any()
    print("[PASS] binary admission blocks unverified data")


def _verify_data_gate():
    report = build_data_integrity_report()
    assert {"gate", "required", "passed", "detail", "artifact"}.issubset(report)
    assert data_verified(report) is False
    outputs = save_data_integrity_artifacts()
    assert all(Path(path).exists() for path in outputs)
    print("[PASS] objective data gate and whitepaper artifacts")


if __name__ == "__main__":
    main()
