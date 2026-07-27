"""Stage-3 checks for SCAP soft penalties and small-account utility."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.small_capital_aggressive import attach_scap_candidate_utility


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> None:
    candidates = pd.DataFrame([
        {"symbol": "cheap", "alpha": 0.90, "comparable_expected_alpha": 0.050, "comparable_alpha_lcb": 0.035, "comparable_value_horizon_days": 10, "mainline_v3_one_lot_cash_required": 2_000.0, "volatility_20": 0.02, "amount_ma20": 8_000_000.0, "ret_5": 0.01, "ret_20": 0.03},
        {"symbol": "expensive", "alpha": 0.90, "comparable_expected_alpha": 0.050, "comparable_alpha_lcb": 0.035, "comparable_value_horizon_days": 10, "mainline_v3_one_lot_cash_required": 7_500.0, "volatility_20": 0.04, "amount_ma20": 2_000_000.0, "ret_5": -0.08, "ret_20": -0.12},
        {"symbol": "lower_alpha", "alpha": 0.70, "comparable_expected_alpha": 0.020, "comparable_alpha_lcb": 0.010, "comparable_value_horizon_days": 10, "mainline_v3_one_lot_cash_required": 2_000.0, "volatility_20": 0.02, "amount_ma20": 8_000_000.0, "ret_5": 0.01, "ret_20": 0.03},
    ])
    candidates["entry_calibration_state_10d"] = "calibrated"
    candidates["forecast_authority_weight_10d"] = 1.0
    result = attach_scap_candidate_utility(
        candidates,
        alpha_score_column="alpha",
        available_cash=20_000.0,
        nominal_nav=20_000.0,
        min_cash_buffer=2_000.0,
        single_position_soft_cap=0.25,
        single_position_hard_cap=0.40,
        candidate_minimum_commission=5.0,
    ).set_index("symbol")
    _check(len(result) == 3, "soft penalties do not delete candidates")
    _check(result.loc["expensive", "scap_concentration_penalty"] > 0.0, "high one-lot concentration is penalized")
    _check(result.loc["cheap", "scap_concentration_penalty"] == 0.0, "small one-lot weight has no concentration penalty")
    _check(result.loc["expensive", "scap_soft_quality_penalty"] > result.loc["cheap", "scap_soft_quality_penalty"], "volatile declining illiquid candidate receives a larger soft penalty")
    _check(result.loc["expensive", "scap_risk_penalty_amount"] > result.loc["cheap", "scap_risk_penalty_amount"], "larger concentrated lot receives a larger yuan risk penalty")
    _check(result.loc["cheap", "scap_candidate_utility"] > result.loc["lower_alpha", "scap_candidate_utility"], "calibrated return LCB remains the primary reward")
    _check((result["scap_overlap_penalty_state"] == "portfolio_optimizer_pending").all(), "unimplemented overlap is disclosed rather than fabricated")


if __name__ == "__main__":
    main()
