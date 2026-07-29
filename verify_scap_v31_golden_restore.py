"""Focused regression contracts carried forward into SCAP-V3.2."""
from dataclasses import replace

import pandas as pd

from config import get_backtest_capital_profile
from functions.decision_council.action_utility import round_trip_cost_amount
from functions.decision_council.integer_action_optimizer import (
    optimize_action_proposals,
)
from functions.decision_council.scap_v2_contracts import (
    ActionProposal,
    ExposureAuthorization,
)
from functions.decision_council.scap_v31_authority import (
    attach_scap_v31_authority,
)


def passed(message):
    print(f"[PASS] {message}")


profile = get_backtest_capital_profile("small_capital_lean")
assert profile["min_cash_buffer"] == 1_000.0
assert profile["minimum_commission"] == 5.0
one_way_doubled = round_trip_cost_amount(
    symbol="sh600000",
    price=10.0,
    shares=100,
    trade_date="2025-01-10",
    cost_profile=profile,
)
assert one_way_doubled >= 10.0
passed("one immutable Lean profile drives buffer and minimum commission")

base = {
    "scap_expected_return_point": 0.03,
    "forecast_cluster_se_10d": 0.01,
    "forecast_rank_ic_10d": 0.05,
    "forecast_calibration_slope_10d": 0.50,
    "forecast_drift_streak_10d": 0,
    "entry_calibration_state_10d": "calibrated",
    "comparable_alpha_lcb": 0.01,
    "comparable_value_contract": "pit_factor_family_return_v1",
}
authority_frame = pd.DataFrame(
    [
        {
            **base,
            "symbol": "A",
            "entry_calibration_effective_sample_size_10d": 100,
            "entry_calibration_unique_session_count_10d": 70,
        },
        {
            **base,
            "symbol": "B",
            "entry_calibration_effective_sample_size_10d": 50,
            "entry_calibration_unique_session_count_10d": 25,
        },
        {
            **base,
            "symbol": "C",
            "entry_calibration_effective_sample_size_10d": 10,
            "entry_calibration_unique_session_count_10d": 10,
        },
        {
            **base,
            "symbol": "D",
            "entry_calibration_effective_sample_size_10d": 100,
            "entry_calibration_unique_session_count_10d": 70,
            "forecast_rank_ic_10d": -0.05,
            "forecast_drift_streak_10d": 3,
        },
    ]
)
scored = attach_scap_v31_authority(authority_frame).set_index("symbol")
assert scored["scap_v31_authority_tier"].to_dict() == {
    "A": "A",
    "B": "B",
    "C": "C",
    # Drift revokes calibrated A/B authority, but it must not erase an
    # independently positive PIT fallback distribution.
    "D": "C",
}
assert int(scored.at["B", "scap_v31_max_lots"]) == 1
assert int(scored.at["C", "scap_v31_max_lots"]) == 1
passed("A/B/C authority and independent PIT fallback rights are explicit")
assert profile["scap_tier_c_max_names"] == 5
assert profile["scap_exploration_exposure_cap"] == 1.0
passed("A/B/C authority no longer creates a hidden two-name portfolio cap")


def proposal(symbol, thesis, robust=20.0):
    return ActionProposal(
        proposal_id=f"d|{symbol}|entry",
        decision_id="d",
        symbol=symbol,
        action_type="new_entry",
        source_module="verify",
        requested_lots=1,
        baseline_action="hold_cash",
        horizon_sessions=10,
        expected_net_profit_amount=robust,
        robust_net_profit_amount=robust,
        downside_cvar_amount=100.0,
        exact_cost_amount=10.0,
        funding_cash_amount=2_000.0,
        exposure_delta=0.10,
        authority_tier="A",
        thesis=thesis,
    )


authorization = ExposureAuthorization(
    decision_id="d",
    nav_amount=20_000.0,
    risk_exposure_ceiling=0.90,
    current_cash_amount=10_000.0,
    cash_buffer_amount=1_000.0,
    per_name_structural_cap=0.40,
    per_name_stress_budget_amount=3_200.0,
    portfolio_stress_budget_amount=8_000.0,
    new_entry_allowed=True,
    add_allowed=True,
    replacement_allowed=False,
)
current_weights = {"H1": 0.10, "H2": 0.10, "H3": 0.10}
current_lots = {"H1": 1, "H2": 1, "H3": 1}
theses = {"H1": "momentum", "H2": "momentum", "H3": "momentum", "N": "value"}
plan = optimize_action_proposals(
    (proposal("N", "value"),),
    authorization=authorization,
    current_lots_by_symbol=current_lots,
    current_weights_by_symbol=current_weights,
    current_exposure=0.30,
    max_positions=5,
    thesis_by_symbol=theses,
    max_names_per_thesis=3,
)
assert plan.selected_proposal_ids == ("d|N|entry",)
assert plan.constraint_slacks["buy_plan_dominates_nonbuy"] == 1
passed("inherited thesis excess does not block a non-worsening new thesis")

blocked = optimize_action_proposals(
    (proposal("M4", "momentum"),),
    authorization=authorization,
    current_lots_by_symbol=current_lots,
    current_weights_by_symbol=current_weights,
    current_exposure=0.30,
    max_positions=5,
    thesis_by_symbol={**theses, "M4": "momentum"},
    max_names_per_thesis=3,
)
assert not blocked.selected_proposal_ids
assert blocked.rejected_proposals[0]["reason"] == "thesis_hard_cap_non_worsening"
passed("thesis hard cap blocks only further deterioration and records the reason")

c_proposal = replace(proposal("C3", "value"), authority_tier="C")
c_allowed = optimize_action_proposals(
    (c_proposal,),
    authorization=replace(authorization, tier_c_max_names=0),
    current_lots_by_symbol={"C1": 1, "C2": 1},
    current_weights_by_symbol={"C1": 0.25, "C2": 0.25},
    current_exposure=0.50,
    max_positions=5,
    thesis_by_symbol={"C1": "momentum", "C2": "value", "C3": "quality"},
)
assert c_allowed.selected_proposal_ids == ("d|C3|entry",)
passed("C-name budget fields are audit-only and cannot veto a positive third C name")

risk_dominated = optimize_action_proposals(
    (proposal("R", "quality", robust=5.0),),
    authorization=authorization,
    current_lots_by_symbol={"H": 1},
    current_weights_by_symbol={"H": 0.30},
    current_exposure=0.30,
    max_positions=5,
    thesis_by_symbol={"H": "momentum", "R": "quality"},
    covariance_matrix=pd.DataFrame(
        [[0.04, 0.04], [0.04, 0.04]],
        index=["H", "R"],
        columns=["H", "R"],
    ),
)
assert not risk_dominated.selected_proposal_ids
assert risk_dominated.constraint_slacks["buy_plan_dominates_nonbuy"] == 0
assert (
    risk_dominated.constraint_slacks["best_feasible_buy_robust_objective"]
    < risk_dominated.constraint_slacks[
        "best_feasible_nonbuy_robust_objective"
    ]
)
passed("liveness consumes exact post-covariance plan dominance")

print("SCAP-V3.2 carried-forward golden verification passed.")
