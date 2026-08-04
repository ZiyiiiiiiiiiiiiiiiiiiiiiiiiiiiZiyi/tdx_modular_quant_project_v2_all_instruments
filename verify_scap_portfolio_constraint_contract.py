"""Focused properties for SCAP policy/projection/deployment contracts."""
from __future__ import annotations

from types import SimpleNamespace

from functions.decision_council.exposure_contract import resolve_policy_band
from functions.decision_council.portfolio_constraint_contract import (
    authorize_recovery,
    project_mandatory_actions,
    resolve_conditional_deployment_bounds,
)


def passed(message: str) -> None:
    print(f"[PASS] {message}")


policy = resolve_policy_band(
    risk_level="normal",
    structural_regime_level="bull",
    policy_bands={
        "normal_neutral": {
            "holding_floor": 3,
            "holding_target": 4,
            "exposure_lower": 0.60,
            "exposure_target": 0.75,
            "exposure_upper": 0.85,
            "disaster_ceiling": 0.90,
        }
    },
)
assert policy.holding_floor == 3 and policy.exposure_target == 0.75
passed("configured policy is consumed without a database or name-based inference")

mandatory = tuple(
    SimpleNamespace(
        proposal_id=f"exit_{index}",
        symbol=f"held_{index}",
        action_type="hard_exit",
        must_execute=True,
        executable=True,
        sell_cash_released_amount=2_000.0,
    )
    for index in range(4)
)
projection = project_mandatory_actions(
    current_lots={f"held_{index}": 100 for index in range(4)},
    current_weights={f"held_{index}": 0.125 for index in range(4)},
    current_cash=10_000.0,
    proposals=mandatory,
)
assert projection.post_mandatory_holding_count == 0
assert projection.post_mandatory_exposure == 0.0
assert projection.post_mandatory_cash == 18_000.0
passed("four mandatory exits are projected before recovery authorization")

entries = tuple(
    SimpleNamespace(
        proposal_id=f"buy_{index}",
        symbol=f"new_{index}",
        action_type="new_entry",
        executable=True,
        robust_net_profit_amount=10.0 + index,
        authority_penalty_amount=1.0,
        exposure_delta=0.15,
    )
    for index in range(4)
)
bounds = resolve_conditional_deployment_bounds(
    policy_band=policy,
    mandatory_projection=projection,
    hard_holding_ceiling=5,
    hard_exposure_ceiling=0.90,
    positive_feasible_proposals=entries,
    wealth_epsilon_amount=1.0,
)
assert bounds.conditional_holding_floor == 3
assert abs(bounds.conditional_exposure_floor - 0.60) < 1e-12
recovery = authorize_recovery(
    decision_id="fixture",
    mandatory_projection=projection,
    bounds=bounds,
    configured_max_new_names=1,
    configured_daily_exposure_cap=0.15,
    deadline_sessions=5,
    safety_blocked=False,
)
assert recovery.authorized
assert recovery.max_new_names_today == 3
assert abs(recovery.max_buy_exposure_today - 0.75) < 1e-12
passed("post-exit deficit can recover the conditional floor in the same plan")

continued = authorize_recovery(
    decision_id="fixture_next",
    mandatory_projection=projection,
    bounds=bounds,
    configured_max_new_names=1,
    configured_daily_exposure_cap=0.15,
    deadline_sessions=5,
    safety_blocked=False,
    prior_episode_id=recovery.episode_id,
    prior_episode_day=recovery.episode_day,
)
assert continued.episode_id == recovery.episode_id
assert continued.episode_day == 2
passed("recovery window has persistent episode identity and session progression")

negative_entries = tuple(
    SimpleNamespace(
        proposal_id=f"bad_{index}",
        symbol=f"bad_{index}",
        action_type="new_entry",
        executable=True,
        robust_net_profit_amount=-1.0,
        authority_penalty_amount=0.0,
        exposure_delta=0.15,
    )
    for index in range(3)
)
no_value_bounds = resolve_conditional_deployment_bounds(
    policy_band=policy,
    mandatory_projection=projection,
    hard_holding_ceiling=5,
    hard_exposure_ceiling=0.90,
    positive_feasible_proposals=negative_entries,
    wealth_epsilon_amount=1.0,
)
assert no_value_bounds.conditional_holding_floor == 3
assert no_value_bounds.policy_holding_floor == 3
assert not no_value_bounds.policy_floor_feasible
assert no_value_bounds.holding_floor_shortfall_reason == "positive_feasible_candidate_shortfall"
passed("candidate quality cannot silently rewrite the configured holding floor")

try:
    resolve_policy_band(
        risk_level="normal",
        structural_regime_level="bull",
        policy_bands={
            "normal_neutral": {
                "holding_floor": 4,
                "holding_target": 3,
                "exposure_lower": 0.70,
                "exposure_target": 0.60,
                "exposure_upper": 0.80,
                "disaster_ceiling": 0.90,
            }
        },
    )
except ValueError:
    passed("invalid holding/exposure policy fails closed")
else:
    raise AssertionError("invalid policy must fail")

print("[PASS] SCAP portfolio constraint contract verification completed")
