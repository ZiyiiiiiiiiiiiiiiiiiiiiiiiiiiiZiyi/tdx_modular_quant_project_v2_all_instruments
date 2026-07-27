"""Focused verification for common-baseline monetary SCAP utility."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.action_utility import build_incremental_action_utility
from functions.decision_council.small_capital_aggressive import (
    attach_scap_candidate_utility,
    select_scap_one_lot_portfolio,
)
from functions.decision_council.policy import _select_scap_discrete_entries
from functions.decision_council.runtime_integrity_audit import (
    build_runtime_integrity_audit,
)


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main():
    utility = build_incremental_action_utility(
        action_type="new_entry",
        notional=1_000.0,
        expected_return_point=0.03,
        expected_return_lcb=0.02,
        estimated_total_cost=12.0,
        horizon_days=10,
    )
    check(abs(utility.incremental_terminal_wealth - 8.0) < 1e-9, "utility is incremental terminal wealth in yuan")
    check(utility.baseline_terminal_wealth == 1_000.0, "hold-cash is the common baseline")
    aggressive_utility = build_incremental_action_utility(
        action_type="new_entry",
        notional=1_000.0,
        expected_return_point=0.03,
        expected_return_lcb=-0.01,
        estimated_total_cost=12.0,
        horizon_days=10,
        decision_return_basis="point",
    )
    check(
        abs(aggressive_utility.incremental_terminal_wealth - 18.0) < 1e-9,
        "aggressive point basis maximizes expected cost-after profit",
    )
    check(
        aggressive_utility.expected_return_lcb == -0.01
        and aggressive_utility.decision_return_basis == "point",
        "point basis preserves the conservative LCB as a separate diagnostic",
    )

    frame = pd.DataFrame(
        {
            "symbol": ["sz000001", "sz000002", "sz000003"],
            "score": [0.9, 0.8, 0.7],
            "mainline_v3_one_lot_cash_required": [1_000.0, 1_000.0, 1_000.0],
            "mainline_v3_minimum_buy_quantity": [100, 100, 100],
            "comparable_expected_alpha": [0.05, 0.04, pd.NA],
            "comparable_alpha_lcb": [0.04, 0.03, pd.NA],
            "comparable_value_horizon_days": [10, 10, 10],
            "entry_calibration_state_10d": ["calibrated", "calibrated", "insufficient"],
            "forecast_authority_weight_10d": [1.0, 1.0, 0.0],
            "volatility_20": [0.02, 0.02, 0.02],
            "amount_ma20": [1e8, 1e8, 1e8],
            "industry": ["bank", "bank", "tech"],
        }
    )
    result = attach_scap_candidate_utility(
        frame,
        alpha_score_column="score",
        available_cash=5_000.0,
        nominal_nav=20_000.0,
        min_cash_buffer=500.0,
    )
    check(result.loc[0, "scap_candidate_utility"] > 0.0, "calibrated positive LCB can produce positive yuan utility")
    check(result.loc[2, "scap_candidate_utility"] <= 0.0, "missing return calibration fails closed")
    check(result.loc[2, "scap_utility_calibration_state"] == "insufficient", "missing calibration state is explicit")
    aggressive = attach_scap_candidate_utility(
        frame,
        alpha_score_column="score",
        available_cash=5_000.0,
        nominal_nav=20_000.0,
        min_cash_buffer=500.0,
        candidate_reward_basis="point",
    )
    check(
        (aggressive["scap_decision_return_basis"] == "point").all(),
        "SCAP new-entry reward basis is explicit in every candidate row",
    )

    corr = pd.DataFrame(
        [[1.0, 0.99, 0.0], [0.99, 1.0, 0.0], [0.0, 0.0, 1.0]],
        index=frame["symbol"],
        columns=frame["symbol"],
    )
    selection = select_scap_one_lot_portfolio(
        result,
        eligible_mask=pd.Series([True, True, True]),
        available_cash=2_500.0,
        min_cash_buffer=0.0,
        remaining_slots=2,
        correlation_matrix=corr,
        correlation_penalty_rate=1.0,
    )
    selected_symbols = set(result.loc[list(selection.selected_indices), "symbol"])
    check(not {"sz000001", "sz000002"}.issubset(selected_symbols), "portfolio optimizer penalizes highly correlated joint selection")
    check(selection.interaction_penalty >= 0.0, "interaction penalty is auditable")

    discrete = pd.DataFrame(
        {
            "symbol": ["A", "B", "C"],
            "mainline_v3_one_lot_weight": [0.20, 0.30, 0.25],
            "scap_candidate_utility": [5.0, 6.0, 4.0],
        }
    )
    chosen = _select_scap_discrete_entries(
        discrete,
        incremental_exposure_cap=0.50,
    )
    check(chosen == {"A", "B"}, "whole-lot subset maximises utility under the exposure cap")
    check(
        discrete.loc[discrete["symbol"].isin(chosen), "mainline_v3_one_lot_weight"].sum()
        <= 0.50 + 1e-12,
        "whole-lot subset cannot cross its authorised exposure",
    )

    integrity = build_runtime_integrity_audit(
        execution_ledger=pd.DataFrame(),
        account_audit=pd.DataFrame(
            {"reconciliation_error": [0.0, 0.0, 0.0]}
        ),
        daily_result=pd.DataFrame(
            {
                "date": ["2025-01-02", "2025-01-03", "2025-01-06"],
                "holding_count": [0, 2, 2],
                "actual_exposure": [0.0, 0.67, 0.48],
                "effective_target_exposure_cap": [0.50, 0.50, 0.50],
            }
        ),
        max_positions=5,
    )
    exposure_check = integrity[
        integrity["check"].eq("execution_exposure_authorization")
    ].iloc[0]
    check(
        not bool(exposure_check["passed"]),
        "integrity audit detects execution exposure above the preceding decision cap",
    )


if __name__ == "__main__":
    main()
