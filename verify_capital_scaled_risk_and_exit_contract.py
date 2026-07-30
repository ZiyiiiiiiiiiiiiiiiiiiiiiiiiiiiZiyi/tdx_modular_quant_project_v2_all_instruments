"""Contract checks for capital-scaled concentration, catch-up, and exits."""
from __future__ import annotations

import numpy as np
import pandas as pd

from functions.decision_council.allocation import _apply_covariance_risk_budget
from functions.decision_council.exposure_catchup import decide_exposure_catchup
from functions.decision_council.position_lifecycle import resolve_scap_loss_limits
from functions.decision_council.quality_reports import build_portfolio_constraint_report
from functions.decision_council.scap_v31_authority import attach_scap_v31_authority


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


balanced = pd.DataFrame(
    {"symbol": [f"s{i}" for i in range(10)], "target_weight": [0.08] * 10}
)
balanced_cov = pd.DataFrame(
    np.eye(10) * 0.0004,
    index=balanced["symbol"],
    columns=balanced["symbol"],
)
balanced_diag = _apply_covariance_risk_budget(
    balanced,
    covariance_matrix=balanced_cov,
    shrinkage=0.30,
    max_risk_contribution=0.35,
)
check(
    balanced_diag["risk_effective_n_ratio"] > 0.99,
    "balanced ten-name risk has scale-normalized effective N near one",
)
check(
    balanced_diag["top20pct_risk_contribution_sum"] <= 0.21,
    "top-20-percent risk share scales with portfolio breadth",
)
check(
    not balanced_diag["risk_catchup_block"],
    "balanced large portfolio is not blocked by the legacy Top-5/8-name rule",
)

concentrated = pd.DataFrame(
    {"symbol": [f"c{i}" for i in range(10)], "target_weight": [0.70] + [0.01] * 9}
)
concentrated_cov = pd.DataFrame(
    np.eye(10) * 0.0004,
    index=concentrated["symbol"],
    columns=concentrated["symbol"],
)
concentrated_diag = _apply_covariance_risk_budget(
    concentrated,
    covariance_matrix=concentrated_cov,
    shrinkage=0.30,
    max_risk_contribution=0.35,
)
check(
    bool(concentrated_diag["risk_catchup_block"])
    or float(concentrated.iloc[0]["target_weight"]) < 0.70,
    "concentrated portfolio is either repaired or blocked by normalized risk shape",
)

catchup = decide_exposure_catchup(
    actual_exposure=0.20,
    target_exposure=0.85,
    risk_level="normal",
    structural_regime_level="bull",
    market_liquidity_stress_ratio=0.0,
    qualified_entry_count=10,
    transition_only=False,
    trailing_buy_accuracy_5d=0.60,
    risk_contribution_gate_pass=True,
    top20pct_risk_contribution_sum=0.20,
    risk_effective_n_ratio=1.0,
    risk_symbol_count=10,
    hard_risk_gate_enabled=True,
)
check(catchup.catchup_allowed, "normalized healthy risk permits exposure catch-up")
blocked_catchup = decide_exposure_catchup(
    actual_exposure=0.20,
    target_exposure=0.85,
    risk_level="normal",
    structural_regime_level="bull",
    market_liquidity_stress_ratio=0.0,
    qualified_entry_count=10,
    transition_only=False,
    trailing_buy_accuracy_5d=0.60,
    risk_contribution_gate_pass=True,
    top20pct_risk_contribution_sum=0.70,
    risk_effective_n_ratio=0.30,
    risk_symbol_count=20,
    hard_risk_gate_enabled=True,
)
check(
    not blocked_catchup.catchup_allowed,
    "poor normalized risk blocks catch-up regardless of absolute holding count",
)

portfolio_report = build_portfolio_constraint_report(
    pd.DataFrame(
        [
            {
                "date": "2025-01-02",
                "configured_max_positions": 20,
                "holding_count": 10,
                "sleeve_effective_n": 9.0,
                "sleeve_effective_n_ratio": 0.90,
                "account_effective_n": 3.0,
                "top1_account_weight": 0.30,
                "top5_account_weight_sum": 0.50,
                "top20pct_sleeve_weight_sum": 0.20,
                "actual_exposure": 0.85,
            }
        ]
    )
)
check(
    bool(portfolio_report.iloc[0]["constraint_pass"]),
    "portfolio research gate uses sleeve shape rather than fixed Top-1 or cash-distorted effective N",
)
check(
    abs(float(portfolio_report.iloc[0]["effective_n_required"]) - 6.5) < 1e-12,
    "effective-N requirement scales with active holding count",
)

profile = {
    "scap_loss_stop": -0.18,
    "scap_loss_stop_mode": "adaptive_volatility_or_disaster_floor",
    "scap_loss_soft_base": -0.16,
    "scap_loss_tail_tightening": 0.04,
}
low_tail_soft, low_tail_disaster = resolve_scap_loss_limits(
    profile, tail_risk_proxy=0.0, disaster_floor=-0.18
)
high_tail_soft, high_tail_disaster = resolve_scap_loss_limits(
    profile, tail_risk_proxy=1.0, disaster_floor=-0.18
)
check(high_tail_soft > low_tail_soft, "higher tail risk tightens the confirmed soft stop")
check(
    low_tail_disaster == high_tail_disaster == -0.18,
    "adaptive stop never widens the immediate disaster floor",
)

authority_input = pd.DataFrame(
    [
        {
            "symbol": "tier_a",
            "entry_calibration_effective_sample_size_10d": 100,
            "entry_calibration_unique_session_count_10d": 80,
            "forecast_rank_ic_10d": 0.1,
            "forecast_calibration_slope_10d": 0.8,
            "forecast_drift_streak_10d": 0,
            "entry_calibration_state_10d": "calibrated",
            "scap_expected_return_point": 0.02,
            "forecast_cluster_se_10d": 0.01,
        },
        {
            "symbol": "tier_b",
            "entry_calibration_effective_sample_size_10d": 50,
            "entry_calibration_unique_session_count_10d": 30,
            "forecast_rank_ic_10d": 0.1,
            "forecast_calibration_slope_10d": 0.8,
            "forecast_drift_streak_10d": 0,
            "entry_calibration_state_10d": "recovering",
            "scap_expected_return_point": 0.02,
            "forecast_cluster_se_10d": 0.01,
        },
    ]
)
authority = attach_scap_v31_authority(authority_input).set_index("symbol")
check(
    authority.at["tier_a", "scap_v31_decision_expected_return"]
    > authority.at["tier_b", "scap_v31_decision_expected_return"],
    "higher-evidence A tier receives a smaller uncertainty haircut than B",
)

print("Capital-scaled risk and exit contract verification passed.")
