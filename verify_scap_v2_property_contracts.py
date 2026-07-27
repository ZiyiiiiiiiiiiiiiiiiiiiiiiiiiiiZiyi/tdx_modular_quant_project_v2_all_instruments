"""Property tests for SCAP-V2 unit and authority contracts."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.mainline_v3 import apply_mainline_v3_entry_policy
from functions.decision_council.entry_calibration import RollingEntryCalibrator
from functions.decision_council.integer_action_optimizer import optimize_action_proposals
from functions.decision_council.cash_reservation_ledger import CashReservationLedger
from functions.decision_council.scap_v2_contracts import (
    ActionProposal,
    ExposureAuthorization,
    ForecastDistribution,
    ScoreContract,
    validate_score_columns,
)


def _pass(message: str) -> None:
    print(f"[PASS] {message}")


ScoreContract(
    symbol="sz000001",
    as_of_date="2025-01-02",
    ranking_score=0.75,
    score_authority="cabinet_native_final_score",
    coverage=1.0,
)
_pass("dimensionless score contract accepts a valid score")

try:
    ScoreContract(
        symbol="sz000001",
        as_of_date="2025-01-02",
        ranking_score=125.0,
        score_authority="yuan_utility",
        coverage=1.0,
    )
except ValueError:
    _pass("yuan utility cannot enter a score contract")
else:
    raise AssertionError("out-of-range ranking score was accepted")

try:
    ForecastDistribution(
        symbol="sz000001",
        as_of_date="2025-01-02",
        entry_price_basis="next_executable_open",
        horizon_sessions=10,
        gross_return_mean=0.02,
        gross_return_se=0.01,
        downside_cvar=-0.04,
        p_win_posterior_mean=0.55,
        p_win_lower=0.45,
        effective_sample_size=0.0,
        authority_weight=1.0,
        state="prior_only",
    )
except ValueError:
    _pass("prior-only forecast cannot receive trading authority")
else:
    raise AssertionError("prior-only forecast received authority")

proposal = ActionProposal(
    proposal_id="p1",
    decision_id="d1",
    symbol="sz000001",
    action_type="new_entry",
    source_module="entry",
    requested_lots=1,
    baseline_action="hold_cash",
    horizon_sessions=10,
    expected_net_profit_amount=20.0,
    robust_net_profit_amount=10.0,
    downside_cvar_amount=80.0,
    exact_cost_amount=10.0,
    funding_cash_amount=1000.0,
)
assert proposal.executable
_pass("valid action proposal remains proposal-only and executable")

frame = pd.DataFrame(
    {
        "symbol": ["sz000001", "sz000002"],
        "cabinet_native_final_score": [0.70, 0.80],
        "cabinet_base_entry_score": [0.70, 0.80],
        "cabinet_timing_score": [0.60, 0.70],
        "cabinet_liquidity_health_score": [0.80, 0.80],
        "cabinet_risk_safety_score": [0.70, 0.70],
        "cabinet_strict_entry_score_coverage": [1.0, 1.0],
        "close_nominal": [10.0, 30.0],
        "alpha_percentile": [0.7, 0.8],
        "aggregate_confidence": [0.7, 0.7],
        "volatility_20": [0.02, 0.02],
        "comparable_expected_alpha": [0.03, 0.03],
        "comparable_alpha_lcb": [0.01, 0.01],
        "comparable_value_state": ["calibrated", "calibrated"],
        "comparable_value_horizon_days": [10, 10],
    }
)
scored = apply_mainline_v3_entry_policy(
    frame,
    max_new_candidates=2,
    available_cash=20_000.0,
    nominal_nav=20_000.0,
    min_cash_buffer=2_000.0,
    max_single_position_weight=0.40,
    decision_date="2025-01-02",
    use_scap_candidate_utility=True,
    scap_candidate_reward_basis="lcb",
)
validate_score_columns(scored)
assert float(scored["scap_candidate_utility"].max()) > 1.0
assert float(scored["entry_matrix_score"].max()) <= 1.0
assert scored["entry_matrix_score"].equals(scored["cabinet_native_final_score"])
_pass("SCAP yuan utility no longer overwrites the 0-1 score chain")

prior_frame = frame.copy()
prior_frame["entry_calibration_state_10d"] = "prior_only"
prior_frame["forecast_authority_weight_10d"] = 0.0
prior_scored = apply_mainline_v3_entry_policy(
    prior_frame,
    max_new_candidates=2,
    available_cash=20_000.0,
    nominal_nav=20_000.0,
    min_cash_buffer=2_000.0,
    max_single_position_weight=0.40,
    decision_date="2025-01-02",
    use_scap_candidate_utility=True,
)
assert int(prior_scored["entry_confirmed"].sum()) == 0
assert int(prior_scored["scap_action_candidate"].sum()) == 0
_pass("zero-authority prior cannot appear downstream as an optimizer candidate")

calibrator = RollingEntryCalibrator(min_bucket_samples=1, min_global_samples=1)
scheduled = pd.DataFrame(
    {
        "symbol": ["sz000001"],
        "alpha_percentile": [0.9],
        "expected_return_5d": [0.02],
    }
)
calibrator.schedule_candidates(
    scheduled,
    day_index=0,
    horizon_days=2,
    regime_name="neutral",
)
assert calibrator.mature(
    day_index=1,
    price_frame=pd.DataFrame(
        {
            "symbol": ["sz000001"],
            "open_nominal": [10.0],
            "close_nominal": [10.5],
        }
    ),
) == 0
assert calibrator.pending_rows[0]["entry_price"] == 10.0
assert calibrator.mature(
    day_index=2,
    price_frame=pd.DataFrame(
        {
            "symbol": ["sz000001"],
            "open_nominal": [10.6],
            "close_nominal": [11.0],
        }
    ),
) == 1
assert abs(calibrator.history_rows[0]["forward_return"] - 0.10) < 1e-12
assert calibrator.history_rows[0]["entry_price_basis"] == "next_observed_open"
_pass("calibration label starts at the next observed executable-open proxy")

prior = RollingEntryCalibrator().score_candidates(
    scheduled,
    regime_name="neutral",
    horizon_days=10,
)
assert prior.loc[0, "entry_calibration_state_10d"] == "prior_only"
assert prior.loc[0, "forecast_authority_weight_10d"] == 0.0
assert prior.loc[0, "forecast_cost_inclusion_state_10d"] == "gross_only"
_pass("zero-sample prior is gross-only and has zero forecast authority")

drift_calibrator = RollingEntryCalibrator(
    min_bucket_samples=5,
    min_global_samples=5,
)
drift_calibrator.history_rows = [
    {
        "symbol": f"S{index}",
        "entry_day_index": index,
        "horizon_days": 10,
        "forward_return": -0.01 * index,
        "expected_return_5d": 0.01 * index,
        "alpha_bucket": "p90_100",
        "flow_bucket": "flow0",
        "regime_bucket": "neutral_weak",
    }
    for index in range(1, 8)
]
warning = drift_calibrator.score_candidates(
    scheduled.assign(alpha_percentile=0.95),
    regime_name="neutral",
    horizon_days=10,
)
assert warning.loc[0, "entry_calibration_state_10d"] == "calibrated"
assert warning.loc[0, "forecast_authority_weight_10d"] > 0.0
for _ in range(2):
    drift_calibrator._history_version += 1
    drift_calibrator._stats_cache.clear()
    drifted = drift_calibrator.score_candidates(
        scheduled.assign(alpha_percentile=0.95),
        regime_name="neutral",
        horizon_days=10,
    )
assert drifted.loc[0, "entry_calibration_state_10d"] == "drifted"
assert drifted.loc[0, "forecast_authority_weight_10d"] == 0.0
_pass("persistent inverted rank relationship revokes authority after three evaluations")

authorization = ExposureAuthorization(
    decision_id="d2",
    nav_amount=20_000.0,
    risk_exposure_ceiling=0.40,
    cash_buffer_amount=2_000.0,
    per_name_structural_cap=0.40,
    per_name_stress_budget_amount=2_000.0,
    portfolio_stress_budget_amount=4_000.0,
    new_entry_allowed=True,
    add_allowed=True,
    replacement_allowed=True,
)
proposals = tuple(
    ActionProposal(
        proposal_id=f"p{index}",
        decision_id="d2",
        symbol=symbol,
        action_type="new_entry",
        source_module="entry",
        requested_lots=1,
        baseline_action="hold_cash",
        horizon_sessions=10,
        expected_net_profit_amount=profit,
        robust_net_profit_amount=profit,
        downside_cvar_amount=500.0,
        exact_cost_amount=10.0,
        funding_cash_amount=funding,
    )
    for index, (symbol, profit, funding) in enumerate(
        (("A", 80.0, 4_000.0), ("B", 70.0, 4_000.0), ("C", 60.0, 4_000.0))
    )
)
plan = optimize_action_proposals(
    proposals,
    authorization=authorization,
    max_positions=5,
    thesis_by_symbol={"A": "size", "B": "size", "C": "quality"},
    max_names_per_thesis=1,
)
assert set(plan.selected_proposal_ids) == {"p0", "p2"}
assert plan.projected_exposure <= authorization.risk_exposure_ceiling
_pass("unique integer ActionPlan enforces exposure and thesis concentration")

reordered = optimize_action_proposals(
    tuple(reversed(proposals)),
    authorization=authorization,
    max_positions=5,
    thesis_by_symbol={"A": "size", "B": "size", "C": "quality"},
    max_names_per_thesis=1,
)
assert set(reordered.selected_proposal_ids) == set(plan.selected_proposal_ids)
_pass("candidate row order does not change the ActionPlan")

cash_ledger = CashReservationLedger(cash_amount=10_000.0, minimum_buffer=2_000.0)
cash_ledger.reserve("ordinary", 3_000.0)
cash_ledger.reserve(
    "pair-buy",
    4_000.0,
    funding_type="conditional_replacement",
    pair_id="pair-1",
)
cash_ledger.reserve(
    "pair-buy",
    4_000.0,
    funding_type="conditional_replacement",
    pair_id="pair-1",
)
assert cash_ledger.reserved_total == 7_000.0
assert (
    cash_ledger.available(
        excluding_reservation_id="pair-buy",
        conditional_credit=2_500.0,
        after_buffer=True,
    )
    == 7_500.0
)
_pass("cash reservation is idempotent and replacement buy excludes itself once")
