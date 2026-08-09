"""Unique integer action optimizer for SCAP-V2.

The runtime position dimension is supplied by the Web/capital profile.  Small
dimensions use exhaustive bounded search; larger dimensions use an explicitly
labelled beam search.
"""
from __future__ import annotations

from itertools import combinations
import math
from typing import Iterable, Mapping

import pandas as pd

from functions.decision_council.portfolio_scenario_model import (
    evaluate_incremental_scenario_risk,
)
from functions.decision_council.scap_v2_contracts import (
    ActionPlan,
    ActionProposal,
    ExposureAuthorization,
)


PLAN_KEY_ROBUST_INDEX = 9


def optimize_action_proposals(
    proposals: Iterable[ActionProposal],
    *,
    authorization: ExposureAuthorization,
    current_lots_by_symbol: Mapping[str, int] | None = None,
    current_weights_by_symbol: Mapping[str, float] | None = None,
    current_exposure: float = 0.0,
    max_positions: int | None = None,
    thesis_by_symbol: Mapping[str, str] | None = None,
    max_names_per_thesis: int = 2,
    correlation_matrix: pd.DataFrame | None = None,
    covariance_matrix: pd.DataFrame | None = None,
    scenario_return_matrix: pd.DataFrame | None = None,
    covariance_risk_aversion: float = 0.05,
    candidate_limit: int = 12,
    exhaustive_max_positions: int = 5,
    beam_width: int = 256,
    minimum_profit_coverage_ratio: float = 1.25,
    minimum_profit_coverage_probability: float = 0.55,
    coverage_correlation_floor: float = 0.35,
    minimum_coverage_evidence_names: int = 1,
    coverage_mode: str = "diagnostic_shadow",
    incremental_cvar_confidence: float = 0.95,
    incremental_cvar_risk_aversion: float = 0.05,
    model_uncertainty_risk_aversion: float = 0.10,
    calibration_warming_effective_samples: int = 30,
    calibration_mature_effective_samples: int = 100,
    max_new_buy_names: int | None = None,
    max_incremental_buy_exposure: float | None = None,
    minimum_positions: int = 0,
    minimum_exposure: float = 0.0,
    target_positions: int | None = None,
    target_exposure: float | None = None,
    wealth_materiality_epsilon_amount: float = 0.0,
    minimum_active_pool_size: int = 0,
    minimum_effective_n_ratio: float = 0.0,
    minimum_pool_count: int = 0,
) -> ActionPlan:
    """Return the sole strategy-authorized integer ActionPlan.

    Hard-vetoed proposals are rejected before search.  Safety exits may be
    represented with ``action_type='safety_exit'`` and are always included;
    all other actions compete on robust net profit.  The first objective is
    robust CNY profit, followed by lower downside/cost, then higher residual
    cash. Spending more is never a tie-break objective.
    """
    if max_positions is None or int(max_positions) <= 0:
        raise ValueError("max_positions must be supplied by the runtime capital profile")
    max_positions = int(max_positions)
    minimum_positions = min(max(int(minimum_positions), 0), max_positions)
    minimum_exposure = min(max(float(minimum_exposure), 0.0), 1.0)
    target_positions = (
        minimum_positions
        if target_positions is None
        else min(max(int(target_positions), minimum_positions), max_positions)
    )
    target_exposure = (
        minimum_exposure
        if target_exposure is None
        else min(max(float(target_exposure), minimum_exposure), 1.0)
    )
    wealth_materiality_epsilon_amount = max(
        float(wealth_materiality_epsilon_amount),
        0.0,
    )
    # Do not rewrite a product minimum merely because today's dynamic capacity
    # is smaller.  From cash, the optimizer must choose either zero names or a
    # complete minimum pool; an infeasible day remains cash and is audited.
    minimum_active_pool_size = max(int(minimum_active_pool_size), 0)
    minimum_effective_n_ratio = min(
        max(float(minimum_effective_n_ratio), 0.0), 1.0
    )
    minimum_pool_count = max(int(minimum_pool_count), 0)
    items = tuple(proposals)
    current_lots = {
        str(symbol): max(int(lots), 0)
        for symbol, lots in (current_lots_by_symbol or {}).items()
    }
    current_weights = {
        str(symbol): max(float(weight), 0.0)
        for symbol, weight in (current_weights_by_symbol or {}).items()
    }
    if not items:
        return _empty_plan(
            authorization,
            current_lots=current_lots,
            current_weights=current_weights,
            current_exposure=current_exposure,
            max_positions=max_positions,
            minimum_positions=minimum_positions,
            minimum_exposure=minimum_exposure,
            target_positions=target_positions,
            target_exposure=target_exposure,
            wealth_materiality_epsilon_amount=wealth_materiality_epsilon_amount,
            minimum_active_pool_size=minimum_active_pool_size,
            minimum_effective_n_ratio=minimum_effective_n_ratio,
            minimum_pool_count=minimum_pool_count,
        )
    if any(item.decision_id != authorization.decision_id for item in items):
        raise ValueError("all proposals and authorization must share decision_id")
    if len({item.proposal_id for item in items}) != len(items):
        raise ValueError("proposal_id must be unique")
    thesis_map = {str(k): str(v) for k, v in (thesis_by_symbol or {}).items()}
    forced = tuple(
        item
        for item in items
        if item.executable
        and (
            bool(item.must_execute)
            or item.action_type in {"safety_exit", "hard_exit"}
        )
    )
    candidate_pool = tuple(
        item
        for item in items
        if item.executable
        and item not in forced
        and (
            item.robust_net_profit_amount
            - item.authority_penalty_amount
        )
        > 0.0
        and _action_authorized(item.action_type, authorization)
    )
    # A bounded reducer keeps exhaustive enumeration predictable while
    # preserving diverse actions/symbols.
    candidates = _pareto_reduce(
        candidate_pool,
        limit=max(int(candidate_limit), 1),
    )
    reduced_ids = {item.proposal_id for item in candidates}
    pair_expected_counts: dict[str, int] = {}
    for item in items:
        if item.replacement_pair_id:
            pair_expected_counts[item.replacement_pair_id] = (
                pair_expected_counts.get(item.replacement_pair_id, 0) + 1
            )

    effective_covariance = (
        covariance_matrix
        if covariance_matrix is not None
        else correlation_matrix
    )

    def evaluate(selected):
        return _plan_key(
            selected,
            authorization=authorization,
            current_lots=current_lots,
            current_weights=current_weights,
            current_exposure=current_exposure,
            max_positions=max_positions,
            thesis_map=thesis_map,
            max_names_per_thesis=max_names_per_thesis,
            pair_expected_counts=pair_expected_counts,
            covariance_matrix=effective_covariance,
            scenario_return_matrix=scenario_return_matrix,
            covariance_risk_aversion=covariance_risk_aversion,
            minimum_profit_coverage_ratio=minimum_profit_coverage_ratio,
            minimum_profit_coverage_probability=minimum_profit_coverage_probability,
            coverage_correlation_floor=coverage_correlation_floor,
            minimum_coverage_evidence_names=minimum_coverage_evidence_names,
            coverage_mode=coverage_mode,
            incremental_cvar_confidence=incremental_cvar_confidence,
            incremental_cvar_risk_aversion=incremental_cvar_risk_aversion,
            model_uncertainty_risk_aversion=model_uncertainty_risk_aversion,
            calibration_warming_effective_samples=calibration_warming_effective_samples,
            calibration_mature_effective_samples=calibration_mature_effective_samples,
            max_new_buy_names=max_new_buy_names,
            max_incremental_buy_exposure=max_incremental_buy_exposure,
            minimum_positions=minimum_positions,
            minimum_exposure=minimum_exposure,
            target_positions=target_positions,
            target_exposure=target_exposure,
            wealth_materiality_epsilon_amount=wealth_materiality_epsilon_amount,
            minimum_active_pool_size=minimum_active_pool_size,
            minimum_effective_n_ratio=minimum_effective_n_ratio,
            minimum_pool_count=minimum_pool_count,
        )

    best = forced
    best_key = evaluate(forced)
    best_nonbuy_key = best_key
    best_buy_key = None
    best_buy = None
    exact_solver = bool(
        int(max_positions) <= max(int(exhaustive_max_positions), 1)
        and len(candidates) <= 12
    )
    if exact_solver:
        max_optional = min(max(int(max_positions), 0), len(candidates))
        for size in range(1, max_optional + 1):
            for optional in combinations(candidates, size):
                selected = forced + optional
                key = evaluate(selected)
                if key is None:
                    continue
                if any(_is_buy_action(item.action_type) for item in selected):
                    if best_buy_key is None or key > best_buy_key:
                        best_buy_key = key
                        best_buy = selected
                elif best_nonbuy_key is None or key > best_nonbuy_key:
                    best_nonbuy_key = key
                if best_key is None or key > best_key:
                    best, best_key = selected, key
        full_universe_optimality = len(candidates) == len(candidate_pool)
        solver_status = (
            "optimal_full_universe_exhaustive"
            if full_universe_optimality
            else "optimal_reduced_universe_exhaustive"
        )
    else:
        full_universe_optimality = False
        states: dict[tuple[str, ...], tuple[tuple[ActionProposal, ...], tuple]] = {
            tuple(sorted(item.proposal_id for item in forced)): (forced, best_key)
        }
        units = _candidate_units(candidates)
        for unit in units:
            expanded = dict(states)
            for selected, _ in states.values():
                trial = selected + unit
                key = evaluate(trial)
                if key is None:
                    continue
                ids = tuple(sorted(item.proposal_id for item in trial))
                incumbent = expanded.get(ids)
                if incumbent is None or key > incumbent[1]:
                    expanded[ids] = (trial, key)
            ranked = sorted(
                expanded.values(),
                key=lambda item: item[1],
                reverse=True,
            )
            states = {
                tuple(sorted(item.proposal_id for item in selected)): (
                    selected,
                    key,
                )
                for selected, key in ranked[: max(int(beam_width), 1)]
            }
        for selected, key in states.values():
            if any(_is_buy_action(item.action_type) for item in selected):
                if best_buy_key is None or key > best_buy_key:
                    best_buy_key = key
                    best_buy = selected
            elif best_nonbuy_key is None or key > best_nonbuy_key:
                best_nonbuy_key = key
            if best_key is None or key > best_key:
                best, best_key = selected, key
        solver_status = "feasible_bounded_beam_search"

    selected_ids = {item.proposal_id for item in best}
    selected_optional = tuple(item for item in best if item not in forced)
    selected_marginals = []
    for unit in _candidate_units(selected_optional):
        reduced = tuple(item for item in best if item not in unit)
        reduced_key = evaluate(reduced)
        if best_key is not None and reduced_key is not None:
            selected_marginals.append(
                float(
                    best_key[PLAN_KEY_ROBUST_INDEX]
                    - reduced_key[PLAN_KEY_ROBUST_INDEX]
                )
            )
    rejected_marginals = []
    rejected_marginal_by_id: dict[str, float] = {}
    for item in candidates:
        if item.proposal_id in selected_ids:
            continue
        expanded_key = evaluate(best + (item,))
        if best_key is not None and expanded_key is not None:
            marginal = float(
                expanded_key[PLAN_KEY_ROBUST_INDEX]
                - best_key[PLAN_KEY_ROBUST_INDEX]
            )
            rejected_marginals.append(marginal)
            rejected_marginal_by_id[item.proposal_id] = marginal
    minimum_selected_marginal = (
        min(selected_marginals) if selected_marginals else 0.0
    )
    maximum_rejected_marginal = (
        max(rejected_marginals) if rejected_marginals else 0.0
    )
    rejected = tuple(
        {
            "proposal_id": item.proposal_id,
            "symbol": item.symbol,
            "action_type": item.action_type,
            "reason": _rejection_reason(
                item,
                authorization,
                selected_ids,
                reduced_ids=reduced_ids,
                current_weights=current_weights,
                current_exposure=current_exposure,
                current_lots=current_lots,
                max_positions=max_positions,
                thesis_map=thesis_map,
                thesis_hard_max=max_names_per_thesis,
            ),
            "marginal_utility_amount": rejected_marginal_by_id.get(
                item.proposal_id
            ),
            "robust_net_profit_amount": float(item.robust_net_profit_amount),
            "downside_cvar_amount": float(item.downside_cvar_amount),
            "lifecycle_cost_amount": float(item.lifecycle_cost_amount),
            "coverage_evidence_authorized": bool(
                item.coverage_evidence_authorized
            ),
        }
        for item in items
        if item.proposal_id not in selected_ids
    )
    target_lots = dict(current_lots)
    for item in best:
        if item.action_type in {"exit", "hard_exit", "safety_exit", "replacement_sell"}:
            target_lots[item.symbol] = 0
        else:
            target_lots[item.symbol] = target_lots.get(item.symbol, 0) + int(
                item.requested_lots
            )
    funding = sum(item.funding_cash_amount for item in best)
    cash_release = sum(item.cash_release_amount for item in best)
    expected = sum(item.expected_net_profit_amount for item in best)
    robust = (
        float(best_key[PLAN_KEY_ROBUST_INDEX])
        if best_key is not None
        else 0.0
    )
    downside = sum(max(item.downside_cvar_amount, 0.0) for item in best)
    cost = sum(item.exact_cost_amount for item in best)
    available_cash = (
        float(authorization.current_cash_amount)
        if float(authorization.current_cash_amount) > 0.0
        else authorization.nav_amount
        * max(authorization.risk_exposure_ceiling - current_exposure, 0.0)
    )
    projected_cash = max(available_cash + cash_release - funding, 0.0)
    projected_weights = _projected_weights(best, current_weights)
    projected_exposure = (
        min(sum(projected_weights.values()), 1.0)
        if current_weights
        else min(
            max(
                float(current_exposure)
                + sum(float(item.exposure_delta) for item in best),
                0.0,
            ),
            1.0,
        )
    )
    deployment_gap = max(
        float(authorization.effective_deployment_target)
        - float(projected_exposure),
        0.0,
    )
    selected_buy_symbols = {
        item.symbol
        for item in best
        if _is_buy_action(item.action_type)
    }
    held_symbols = {
        symbol
        for symbol, weight in projected_weights.items()
        if float(weight) > 1e-12
    }
    selected_pools = {
        item.pool_id or item.thesis
        for item in best
        if _is_buy_action(item.action_type) and (item.pool_id or item.thesis)
    }
    selected_pools.update(
        thesis_map.get(symbol, "")
        for symbol in held_symbols
        if thesis_map.get(symbol, "")
    )
    breadth_score = _normalized_breadth_score(
        projected_weights,
        selected_pools,
        max_positions=max_positions,
    )
    positive_weights = [
        float(projected_weights[symbol])
        for symbol in held_symbols
        if float(projected_weights.get(symbol, 0.0)) > 1e-12
    ]
    positive_total = sum(positive_weights)
    planned_effective_n = (
        1.0
        / max(
            sum(
                (weight / max(positive_total, 1e-12)) ** 2
                for weight in positive_weights
            ),
            1e-12,
        )
        if positive_weights
        else 0.0
    )
    authority_penalty = sum(
        max(float(item.authority_penalty_amount), 0.0)
        for item in best
    )
    concentration_penalty = _concentration_penalty(
        projected_weights,
        authorization,
    )
    scenario_risk = evaluate_incremental_scenario_risk(
        best,
        covariance_matrix=effective_covariance,
        scenario_return_matrix=scenario_return_matrix,
        correlation_floor=coverage_correlation_floor,
        cvar_confidence=incremental_cvar_confidence,
        cvar_risk_aversion=incremental_cvar_risk_aversion,
        model_uncertainty_risk_aversion=model_uncertainty_risk_aversion,
        warming_effective_samples=calibration_warming_effective_samples,
        mature_effective_samples=calibration_mature_effective_samples,
    )
    marginal_risk_penalty = float(scenario_risk.scenario_risk_penalty_amount)
    proposal_robust_profit = sum(
        float(item.robust_net_profit_amount) for item in best
    )
    thesis_penalty = _soft_thesis_penalty(
        best,
        projected_weights=projected_weights,
        thesis_map=thesis_map,
        soft_max_names=authorization.thesis_soft_max_names,
    )
    # Deployment gap is a diagnostic/tie-break dimension only.  Charging
    # whole-account NAV for holding cash would make the factual no-trade
    # baseline negative and reintroduce capital-scale-driven forced buying.
    deployment_penalty = 0.0
    coverage = _portfolio_coverage_metrics(
        best,
        covariance_matrix=effective_covariance,
        correlation_floor=coverage_correlation_floor,
        minimum_evidence_names=minimum_coverage_evidence_names,
    )
    coverage_penalty = 0.0
    best_rejected = (
        tuple(best_buy)
        if best_buy is not None
        and {item.proposal_id for item in best_buy} != selected_ids
        else ()
    )
    best_rejected_risk = evaluate_incremental_scenario_risk(
        best_rejected,
        covariance_matrix=effective_covariance,
        scenario_return_matrix=scenario_return_matrix,
        correlation_floor=coverage_correlation_floor,
        cvar_confidence=incremental_cvar_confidence,
        cvar_risk_aversion=incremental_cvar_risk_aversion,
        model_uncertainty_risk_aversion=model_uncertainty_risk_aversion,
        warming_effective_samples=calibration_warming_effective_samples,
        mature_effective_samples=calibration_mature_effective_samples,
    )
    expected_log_growth = math.log1p(
        max(float(robust) / max(float(authorization.nav_amount), 1e-12), -0.999999)
    )
    buy_plan_dominates_nonbuy = bool(
        best_buy_key is not None
        and (best_nonbuy_key is None or best_buy_key > best_nonbuy_key)
    )
    planned_holding_count = sum(
        int(lots) > 0 for lots in target_lots.values()
    )
    holding_floor_violation = max(
        int(minimum_positions) - int(planned_holding_count),
        0,
    )
    exposure_floor_violation = max(
        float(minimum_exposure) - float(projected_exposure),
        0.0,
    )
    initial_holding_count = sum(
        int(lots) > 0 for lots in current_lots.values()
    )
    atomic_pool_violation = (
        max(int(minimum_active_pool_size) - planned_holding_count, 0)
        if initial_holding_count == 0
        and 0 < planned_holding_count < int(minimum_active_pool_size)
        else 0
    )
    required_effective_n = (
        float(minimum_effective_n_ratio) * planned_holding_count
        if planned_holding_count > 0
        else 0.0
    )
    effective_n_violation = max(
        required_effective_n - float(planned_effective_n),
        0.0,
    )
    planned_pool_count = len({value for value in selected_pools if value})
    required_pool_count = (
        min(int(minimum_pool_count), planned_holding_count)
        if planned_holding_count > 0
        else 0
    )
    pool_count_violation = max(
        required_pool_count - planned_pool_count,
        0,
    )
    return ActionPlan(
        decision_id=authorization.decision_id,
        selected_proposal_ids=tuple(item.proposal_id for item in best),
        rejected_proposals=rejected,
        target_lots_by_symbol=target_lots,
        expected_net_profit_amount=expected,
        robust_net_profit_amount=robust,
        downside_cvar_amount=downside,
        exact_cost_amount=cost,
        projected_cash=projected_cash,
        projected_exposure=projected_exposure,
        projected_stress_loss=downside,
        objective_lexicographic_rank=(
            robust,
            -deployment_gap,
            breadth_score,
            expected,
            -downside,
            -cost,
        ),
        constraint_slacks={
            "exposure": max(
                authorization.risk_exposure_ceiling - projected_exposure, 0.0
            ),
            "stress": max(
                authorization.portfolio_stress_budget_amount - downside, 0.0
            ),
            "cash": max(
                available_cash
                + cash_release
                - authorization.cash_buffer_amount
                - funding,
                0.0,
            ),
            "slots": max(
                int(max_positions)
                - sum(1 for lots in target_lots.values() if int(lots) > 0),
                0,
            ),
            "holding_floor": max(
                int(planned_holding_count) - int(minimum_positions),
                0,
            ),
            "exposure_floor": max(
                float(projected_exposure) - float(minimum_exposure),
                0.0,
            ),
            "holding_floor_violation_count": holding_floor_violation,
            "exposure_floor_violation": exposure_floor_violation,
            "minimum_active_pool_size": int(minimum_active_pool_size),
            "planned_effective_n": float(planned_effective_n),
            "required_effective_n": float(
                minimum_effective_n_ratio * planned_holding_count
            ),
            "effective_n_violation": max(
                float(minimum_effective_n_ratio * planned_holding_count)
                - float(planned_effective_n),
                0.0,
            ),
            "atomic_pool_violation_count": int(atomic_pool_violation),
            "planned_pool_count": int(planned_pool_count),
            "required_pool_count": int(required_pool_count),
            "pool_count_violation": int(pool_count_violation),
            "best_feasible_buy_robust_objective": (
                float(best_buy_key[PLAN_KEY_ROBUST_INDEX])
                if best_buy_key is not None
                else 0.0
            ),
            "best_feasible_nonbuy_robust_objective": (
                float(best_nonbuy_key[PLAN_KEY_ROBUST_INDEX])
                if best_nonbuy_key is not None
                else 0.0
            ),
            "buy_plan_dominates_nonbuy": int(buy_plan_dominates_nonbuy),
            "deployment_gap": deployment_gap,
            "breadth_score": breadth_score,
            "authority_penalty_amount": authority_penalty,
            "concentration_penalty_amount": concentration_penalty,
            "marginal_risk_penalty_amount": marginal_risk_penalty,
            "proposal_robust_profit_amount": proposal_robust_profit,
            "thesis_penalty_amount": thesis_penalty,
            "deployment_penalty_amount": deployment_penalty,
            "coverage_penalty_amount": coverage_penalty,
            "profit_coverage_ratio": coverage["profit_coverage_ratio"],
            "profit_coverage_probability_lower": coverage[
                "profit_coverage_probability_lower"
            ],
            "coverage_evidence_name_count": coverage["evidence_name_count"],
            "expected_positive_pnl_amount": coverage[
                "expected_positive_pnl_amount"
            ],
            "expected_loss_pnl_amount": coverage["expected_loss_pnl_amount"],
            "lifecycle_cost_amount": coverage["lifecycle_cost_amount"],
            "expected_log_growth": expected_log_growth,
            "minimum_selected_marginal_utility_amount": minimum_selected_marginal,
            "maximum_rejected_marginal_utility_amount": maximum_rejected_marginal,
            "cash_release_amount": cash_release,
            "solver_candidate_count": len(candidates),
            "solver_original_candidate_count": len(candidate_pool),
            "solver_reduced_candidate_count": len(candidates),
            "solver_beam_width": (
                0 if exact_solver else max(int(beam_width), 1)
            ),
            "solver_reduced_universe_optimality_proven": int(exact_solver),
            "solver_optimality_proven": int(
                exact_solver and full_universe_optimality
            ),
        },
        solver_status=solver_status,
        plan_id=f"{authorization.decision_id}|action_plan",
        optimizer_invocation_count=1,
        deployment_gap=deployment_gap,
        breadth_score=breadth_score,
        authority_penalty_amount=authority_penalty,
        concentration_penalty_amount=concentration_penalty,
        marginal_risk_penalty_amount=marginal_risk_penalty,
        proposal_robust_profit_amount=proposal_robust_profit,
        thesis_penalty_amount=thesis_penalty,
        deployment_penalty_amount=deployment_penalty,
        selected_position_count=sum(
            1 for lots in target_lots.values() if int(lots) > 0
        ),
        coverage_evidence_name_count=int(coverage["evidence_name_count"]),
        expected_positive_pnl_amount=float(coverage["expected_positive_pnl_amount"]),
        expected_loss_pnl_amount=float(coverage["expected_loss_pnl_amount"]),
        lifecycle_cost_amount=float(coverage["lifecycle_cost_amount"]),
        profit_coverage_ratio=float(coverage["profit_coverage_ratio"]),
        profit_coverage_probability_lower=float(
            coverage["profit_coverage_probability_lower"]
        ),
        coverage_penalty_amount=float(coverage_penalty),
        expected_log_growth=float(expected_log_growth),
        minimum_selected_marginal_utility_amount=float(
            minimum_selected_marginal
        ),
        maximum_rejected_marginal_utility_amount=float(
            maximum_rejected_marginal
        ),
        coverage_state=str(coverage["state"]),
        coverage_mode=str(coverage_mode),
        hold_baseline_objective_amount=float(
            scenario_risk.hold_baseline_objective_amount
        ),
        incremental_expected_wealth_amount=float(
            scenario_risk.incremental_expected_wealth_amount
        ),
        incremental_cvar_amount=float(scenario_risk.incremental_cvar_amount),
        model_uncertainty_amount=float(scenario_risk.model_uncertainty_amount),
        scenario_risk_penalty_amount=float(
            scenario_risk.scenario_risk_penalty_amount
        ),
        scenario_evidence_state=str(scenario_risk.evidence_state),
        scenario_contract_id=str(scenario_risk.contract_version),
        scenario_risk_measure=str(scenario_risk.risk_measure_name),
        joint_scenario_count=int(scenario_risk.joint_scenario_count),
        best_rejected_proposal_ids=tuple(
            item.proposal_id for item in best_rejected
        ),
        best_rejected_objective_amount=(
            float(best_buy_key[PLAN_KEY_ROBUST_INDEX])
            if best_rejected and best_buy_key is not None
            else 0.0
        ),
        best_rejected_expected_wealth_amount=float(
            best_rejected_risk.incremental_expected_wealth_amount
        ),
        best_rejected_cvar_amount=float(
            best_rejected_risk.incremental_cvar_amount
        ),
        best_rejected_model_uncertainty_amount=float(
            best_rejected_risk.model_uncertainty_amount
        ),
        risk_model_used=(
            "joint_historical_scenario_cvar"
            if scenario_risk.risk_measure_name == "joint_historical_scenario_cvar"
            else "covariance_with_correlated_tail_loss_proxy"
            if _covariance_complete_for_weights(
                projected_weights,
                effective_covariance,
            )
            else str(authorization.fallback_risk_model)
        ),
        risk_horizon_sessions=int(authorization.risk_horizon_sessions),
        risk_episode_id=str(authorization.risk_episode_id),
        planned_holding_count=int(planned_holding_count),
        holding_floor_violation_count=int(holding_floor_violation),
        exposure_floor_violation=float(exposure_floor_violation),
        wealth_materiality_epsilon_amount=float(
            wealth_materiality_epsilon_amount
        ),
        objective_components={
            "atomic_pool_violation_count": float(atomic_pool_violation),
            "holding_floor_violation_count": float(holding_floor_violation),
            "exposure_floor_violation": float(exposure_floor_violation),
            "effective_n_violation": float(effective_n_violation),
            "pool_count_violation": float(pool_count_violation),
            "robust_wealth_amount": float(robust),
            "target_holding_gap": float(
                abs(int(target_positions) - int(planned_holding_count))
            ),
            "target_exposure_gap": float(
                abs(float(target_exposure) - float(projected_exposure))
            ),
            "breadth_score": float(breadth_score),
            "exact_cost_amount": float(cost),
        },
        sizing_contract_id=next(
            (
                str(proposal.sizing_contract_id)
                for proposal in candidate_pool
                if str(getattr(proposal, "sizing_contract_id", ""))
            ),
            "",
        ),
    )


def _plan_key(
    selected: tuple[ActionProposal, ...],
    *,
    authorization: ExposureAuthorization,
    current_lots: Mapping[str, int],
    current_weights: Mapping[str, float],
    current_exposure: float,
    max_positions: int,
    thesis_map: Mapping[str, str],
    max_names_per_thesis: int,
    pair_expected_counts: Mapping[str, int],
    covariance_matrix: pd.DataFrame | None,
    scenario_return_matrix: pd.DataFrame | None,
    covariance_risk_aversion: float,
    minimum_profit_coverage_ratio: float,
    minimum_profit_coverage_probability: float,
    coverage_correlation_floor: float,
    minimum_coverage_evidence_names: int,
    coverage_mode: str,
    incremental_cvar_confidence: float,
    incremental_cvar_risk_aversion: float,
    model_uncertainty_risk_aversion: float,
    calibration_warming_effective_samples: int,
    calibration_mature_effective_samples: int,
    max_new_buy_names: int | None,
    max_incremental_buy_exposure: float | None,
    minimum_positions: int,
    minimum_exposure: float,
    target_positions: int,
    target_exposure: float,
    wealth_materiality_epsilon_amount: float,
    minimum_active_pool_size: int,
    minimum_effective_n_ratio: float,
    minimum_pool_count: int,
) -> tuple | None:
    by_symbol: dict[str, list[ActionProposal]] = {}
    for item in selected:
        by_symbol.setdefault(item.symbol, []).append(item)
    for actions in by_symbol.values():
        # Multiple lot-size proposals for one symbol are alternatives, not
        # cumulative orders.  Selecting more than one would double-count cash.
        if len(actions) > 1:
            return None
        directions = {
            "sell"
            if item.action_type in {"exit", "hard_exit", "safety_exit", "replacement_sell"}
            else "buy"
            for item in actions
        }
        if len(directions) > 1:
            return None
    selected_pair_counts: dict[str, int] = {}
    for item in selected:
        if item.replacement_pair_id:
            selected_pair_counts[item.replacement_pair_id] = (
                selected_pair_counts.get(item.replacement_pair_id, 0) + 1
            )
    if any(
        count != pair_expected_counts.get(pair_id, count)
        for pair_id, count in selected_pair_counts.items()
    ):
        return None

    symbols = {symbol for symbol, lots in current_lots.items() if int(lots) > 0}
    funding = 0.0
    cash_release = 0.0
    downside = 0.0
    for item in selected:
        if item.action_type in {"exit", "hard_exit", "safety_exit", "replacement_sell"}:
            symbols.discard(item.symbol)
            cash_release += max(float(item.cash_release_amount), 0.0)
        else:
            symbols.add(item.symbol)
            funding += item.funding_cash_amount
        downside += max(item.downside_cvar_amount, 0.0)
    new_buy_names = {
        item.symbol
        for item in selected
        if _is_buy_action(item.action_type)
        and int(current_lots.get(item.symbol, 0)) <= 0
    }
    if max_new_buy_names is not None and len(new_buy_names) > max(
        int(max_new_buy_names), 0
    ):
        return None
    incremental_buy_exposure = sum(
        max(float(item.exposure_delta), 0.0)
        for item in selected
        if _is_buy_action(item.action_type)
    )
    if (
        max_incremental_buy_exposure is not None
        and incremental_buy_exposure
        > max(float(max_incremental_buy_exposure), 0.0) + 1e-12
    ):
        return None
    if len(symbols) > int(max_positions):
        return None
    projected_weights = _projected_weights(selected, current_weights)
    if current_weights:
        if any(
            weight > authorization.per_name_structural_cap + 1e-12
            for weight in projected_weights.values()
        ):
            return None
        projected_exposure = sum(projected_weights.values())
    else:
        projected_exposure = max(
            float(current_exposure)
            + sum(float(item.exposure_delta) for item in selected),
            0.0,
        )
    if projected_exposure > authorization.risk_exposure_ceiling + 1e-12:
        return None
    explicit_cash = float(authorization.current_cash_amount) > 0.0
    available_cash = (
        float(authorization.current_cash_amount)
        if explicit_cash
        else authorization.nav_amount
        * max(authorization.risk_exposure_ceiling - current_exposure, 0.0)
    )
    required_buffer = authorization.cash_buffer_amount if explicit_cash else 0.0
    if funding > max(
        available_cash + cash_release - required_buffer,
        0.0,
    ) + 1e-8:
        return None
    tier_b_exposure = sum(
        max(item.exposure_delta, 0.0)
        for item in selected
        if item.authority_tier == "B"
    )
    exploration_exposure = sum(
        max(item.exposure_delta, 0.0)
        for item in selected
        if item.authority_tier in {"B", "C"}
    )
    tier_c_names = len(
        {
            item.symbol
            for item in selected
            if item.authority_tier == "C" and item.exposure_delta > 0.0
        }
    )
    # V3.2: A/B/C are evidence discounts and starter-size controls. They are
    # audited here but are no longer hidden portfolio-name/exposure vetoes.
    if thesis_map:
        baseline_counts: dict[str, int] = {}
        for symbol, weight in current_weights.items():
            thesis = thesis_map.get(symbol, "")
            if weight > 1e-12 and thesis:
                baseline_counts[thesis] = baseline_counts.get(thesis, 0) + 1
        counts: dict[str, int] = {}
        for symbol in symbols:
            thesis = thesis_map.get(symbol, "")
            if not thesis:
                continue
            counts[thesis] = counts.get(thesis, 0) + 1
        for thesis, count in counts.items():
            baseline = baseline_counts.get(thesis, 0)
            if count > int(max_names_per_thesis) and count > baseline:
                return None

    scenario_risk = evaluate_incremental_scenario_risk(
        selected,
        covariance_matrix=covariance_matrix,
        scenario_return_matrix=scenario_return_matrix,
        correlation_floor=coverage_correlation_floor,
        cvar_confidence=incremental_cvar_confidence,
        cvar_risk_aversion=incremental_cvar_risk_aversion,
        model_uncertainty_risk_aversion=model_uncertainty_risk_aversion,
        warming_effective_samples=calibration_warming_effective_samples,
        mature_effective_samples=calibration_mature_effective_samples,
    )
    if float(scenario_risk.incremental_cvar_amount) > float(
        authorization.portfolio_stress_budget_amount
    ) + 1e-12:
        return None
    robust = float(scenario_risk.incremental_robust_wealth_amount)
    soft_thesis_penalty = _soft_thesis_penalty(
        selected,
        projected_weights=projected_weights,
        thesis_map=thesis_map,
        soft_max_names=authorization.thesis_soft_max_names,
    )
    robust -= soft_thesis_penalty
    robust -= float(scenario_risk.scenario_risk_penalty_amount)
    concentration_penalty = _concentration_penalty(
        projected_weights,
        authorization,
    )
    robust -= concentration_penalty
    deployment_gap = max(
        float(authorization.effective_deployment_target)
        - float(projected_exposure),
        0.0,
    )
    # The no-trade baseline is exactly zero incremental wealth.  Deployment
    # gap may break otherwise equal plans, but never becomes a CNY penalty.
    coverage_mode_normalized = str(coverage_mode).strip().lower()
    if coverage_mode_normalized not in {
        "diagnostic_shadow",
        "diagnostic_only",
        "authorized_ceiling_only",
    }:
        raise ValueError("unsupported profit coverage authority mode")
    active_symbols = {
        symbol
        for symbol, weight in projected_weights.items()
        if float(weight) > 1e-12
    }
    active_pools = {
        item.pool_id or item.thesis
        for item in selected
        if _is_buy_action(item.action_type) and (item.pool_id or item.thesis)
    }
    active_pools.update(
        thesis_map.get(symbol, "")
        for symbol in active_symbols
        if thesis_map.get(symbol, "")
    )
    breadth = _normalized_breadth_score(
        projected_weights,
        active_pools,
        max_positions=max_positions,
    )
    expected = sum(item.expected_net_profit_amount for item in selected)
    cost = sum(item.exact_cost_amount for item in selected)
    residual = max(
        authorization.nav_amount
        * max(authorization.risk_exposure_ceiling - float(current_exposure), 0.0)
        - funding,
        0.0,
    )
    ids = tuple(sorted(item.proposal_id for item in selected))
    holding_floor_violation = max(int(minimum_positions) - len(symbols), 0)
    exposure_floor_violation = max(
        float(minimum_exposure) - float(projected_exposure),
        0.0,
    )
    target_holding_gap = abs(int(target_positions) - len(symbols))
    target_exposure_gap = abs(float(target_exposure) - float(projected_exposure))
    initial_position_count = sum(int(lots) > 0 for lots in current_lots.values())
    planned_position_count = len(symbols)
    # Coverage has deliberately narrow authority: it can veto only expansion
    # above the product target.  It cannot force an entry, penalize cash by
    # account NAV, or fabricate evidence when PIT calibration is unavailable.
    if (
        coverage_mode_normalized == "authorized_ceiling_only"
        and new_buy_names
        and planned_position_count > int(target_positions)
    ):
        coverage = _portfolio_coverage_metrics(
            selected,
            covariance_matrix=covariance_matrix,
            correlation_floor=coverage_correlation_floor,
            minimum_evidence_names=minimum_coverage_evidence_names,
        )
        if (
            int(coverage["evidence_name_count"])
            < int(minimum_coverage_evidence_names)
            or float(coverage["profit_coverage_ratio"])
            < float(minimum_profit_coverage_ratio)
            or float(coverage["profit_coverage_probability_lower"])
            < float(minimum_profit_coverage_probability)
        ):
            return None
    atomic_pool_violation = (
        max(int(minimum_active_pool_size) - planned_position_count, 0)
        if initial_position_count == 0
        and 0 < planned_position_count < int(minimum_active_pool_size)
        else 0
    )
    positive_weights = [
        max(float(projected_weights.get(symbol, 0.0)), 0.0)
        for symbol in symbols
        if float(projected_weights.get(symbol, 0.0)) > 1e-12
    ]
    total_positive_weight = sum(positive_weights)
    effective_n = (
        1.0
        / max(
            sum(
                (weight / max(total_positive_weight, 1e-12)) ** 2
                for weight in positive_weights
            ),
            1e-12,
        )
        if positive_weights
        else 0.0
    )
    required_effective_n = (
        float(minimum_effective_n_ratio) * planned_position_count
        if planned_position_count > 0
        else 0.0
    )
    effective_n_violation = max(required_effective_n - effective_n, 0.0)
    active_pool_names = {
        thesis_map.get(symbol, "")
        for symbol in symbols
        if thesis_map.get(symbol, "")
    }
    required_pool_count = (
        min(int(minimum_pool_count), planned_position_count)
        if planned_position_count > 0
        else 0
    )
    pool_count_violation = max(required_pool_count - len(active_pool_names), 0)
    epsilon = max(float(wealth_materiality_epsilon_amount), 0.0)
    robust_material_bucket = (
        int(math.floor((robust + epsilon * 0.5) / epsilon))
        if epsilon > 0.0
        else robust
    )
    return (
        -atomic_pool_violation,
        -holding_floor_violation,
        -exposure_floor_violation,
        -effective_n_violation,
        -pool_count_violation,
        robust_material_bucket,
        -target_holding_gap,
        -target_exposure_gap,
        breadth,
        robust,
        expected,
        -downside,
        -cost,
        ids,
    )


def _normalized_breadth_score(
    weights: Mapping[str, float],
    pools,
    *,
    max_positions: int,
) -> float:
    """Scale name, effective-N and pool breadth without fixed 4/3 cutoffs."""
    positive = [max(float(value), 0.0) for value in weights.values() if float(value) > 1e-12]
    count = len(positive)
    if count <= 0:
        return 0.0
    total = sum(positive)
    normalized = [value / max(total, 1e-12) for value in positive]
    effective_n = 1.0 / max(sum(value * value for value in normalized), 1e-12)
    capacity = max(int(max_positions), 1)
    name_ratio = min(count / capacity, 1.0)
    effective_ratio = min(effective_n / count, 1.0)
    pool_count = len({str(value) for value in pools if str(value)})
    pool_ratio = min(pool_count / count, 1.0)
    entropy = -sum(value * math.log(max(value, 1e-12)) for value in normalized)
    entropy_ratio = (
        min(entropy / math.log(count), 1.0)
        if count > 1
        else 1.0
    )
    return float(name_ratio + effective_ratio + pool_ratio + entropy_ratio)


def _portfolio_coverage_metrics(
    selected: tuple[ActionProposal, ...],
    *,
    covariance_matrix: pd.DataFrame | None,
    correlation_floor: float,
    minimum_evidence_names: int,
) -> dict[str, float | int | str]:
    """Conservative portfolio profit/loss coverage from PIT proposal evidence.

    Cantelli's one-sided inequality supplies a distribution-free lower bound.
    Dependence inflates Bernoulli variance by at least ``correlation_floor``;
    when a complete covariance block exists its average absolute correlation
    may increase, but never reduce, that conservative floor.
    """
    selected_buys = tuple(
        item for item in selected if _is_buy_action(item.action_type)
    )
    evidence = tuple(
        item
        for item in selected_buys
        if bool(item.coverage_evidence_authorized)
    )
    positive = sum(float(item.expected_positive_pnl_amount) for item in evidence)
    loss = sum(float(item.expected_loss_pnl_amount) for item in evidence)
    # Lifecycle cost is factual for every selected buy.  PIT evidence governs
    # whether profit/loss coverage can be estimated, not whether costs exist.
    lifecycle = sum(float(item.lifecycle_cost_amount) for item in selected_buys)
    denominator = loss + lifecycle
    ratio = positive / denominator if denominator > 1e-12 else 0.0
    minimum_names = max(int(minimum_evidence_names), 1)
    if len(evidence) < minimum_names:
        return {
            "state": "insufficient_pit_coverage_evidence",
            "evidence_name_count": len(evidence),
            "expected_positive_pnl_amount": positive,
            "expected_loss_pnl_amount": loss,
            "lifecycle_cost_amount": lifecycle,
            "profit_coverage_ratio": ratio,
            "profit_coverage_probability_lower": 0.0,
            "dependence_assumption": min(max(float(correlation_floor), 0.0), 1.0),
        }
    variance = 0.0
    for item in evidence:
        probability = min(max(float(item.p_win_lower), 0.0), 1.0)
        win = max(float(item.avg_win_return), 0.0) * float(item.market_notional_amount)
        lose = max(float(item.avg_loss_return), 0.0) * float(item.market_notional_amount)
        variance += probability * (1.0 - probability) * (win + lose) ** 2
    dependence = _coverage_dependence(
        tuple(item.symbol for item in evidence),
        covariance_matrix,
        floor=correlation_floor,
    )
    variance *= 1.0 + max(len(evidence) - 1, 0) * dependence
    mean_net = positive - loss - lifecycle
    probability_lower = (
        mean_net * mean_net / (variance + mean_net * mean_net)
        if mean_net > 0.0 and variance > 0.0
        else (1.0 if mean_net > 0.0 else 0.0)
    )
    return {
        "state": "pit_calibrated_cantelli_lower_bound",
        "evidence_name_count": len(evidence),
        "expected_positive_pnl_amount": positive,
        "expected_loss_pnl_amount": loss,
        "lifecycle_cost_amount": lifecycle,
        "profit_coverage_ratio": ratio,
        "profit_coverage_probability_lower": min(max(probability_lower, 0.0), 1.0),
        "dependence_assumption": dependence,
    }


def _coverage_dependence(
    symbols: tuple[str, ...],
    covariance_matrix: pd.DataFrame | None,
    *,
    floor: float,
) -> float:
    conservative_floor = min(max(float(floor), 0.0), 1.0)
    unique = tuple(dict.fromkeys(str(symbol) for symbol in symbols))
    if len(unique) < 2 or covariance_matrix is None or covariance_matrix.empty:
        return conservative_floor
    if any(
        symbol not in covariance_matrix.index or symbol not in covariance_matrix.columns
        for symbol in unique
    ):
        return conservative_floor
    block = covariance_matrix.loc[list(unique), list(unique)].apply(
        pd.to_numeric, errors="coerce"
    )
    if block.isna().any().any():
        return conservative_floor
    diagonal = [max(float(block.loc[symbol, symbol]), 0.0) ** 0.5 for symbol in unique]
    correlations = []
    for left_index, left in enumerate(unique):
        for right_index in range(left_index + 1, len(unique)):
            scale = diagonal[left_index] * diagonal[right_index]
            if scale > 1e-12:
                correlations.append(abs(float(block.loc[left, unique[right_index]]) / scale))
    empirical = sum(correlations) / len(correlations) if correlations else 0.0
    return min(max(conservative_floor, empirical), 1.0)


def _candidate_units(
    candidates: tuple[ActionProposal, ...],
) -> tuple[tuple[ActionProposal, ...], ...]:
    """Keep paired replacement actions atomic in approximate search."""
    paired: dict[str, list[ActionProposal]] = {}
    singles: list[tuple[ActionProposal, ...]] = []
    for item in candidates:
        if item.replacement_pair_id:
            paired.setdefault(item.replacement_pair_id, []).append(item)
        else:
            singles.append((item,))
    pair_units = [
        tuple(sorted(items, key=lambda item: item.proposal_id))
        for _, items in sorted(paired.items())
    ]
    return tuple(singles + pair_units)


def _concentration_penalty(
    weights: Mapping[str, float],
    authorization: ExposureAuthorization,
) -> float:
    soft_cap = min(
        max(float(authorization.per_name_soft_cap), 0.0),
        float(authorization.per_name_structural_cap),
    )
    excess_square = sum(
        max(float(weight) - soft_cap, 0.0) ** 2
        for weight in weights.values()
    )
    return (
        float(authorization.nav_amount)
        * float(authorization.name_concentration_penalty_rate)
        * excess_square
    )


def _soft_thesis_penalty(
    selected: tuple[ActionProposal, ...],
    *,
    projected_weights: Mapping[str, float],
    thesis_map: Mapping[str, str],
    soft_max_names: int,
) -> float:
    """Return the exact thesis penalty used by the objective ledger."""
    if not thesis_map:
        return 0.0
    counts: dict[str, int] = {}
    for symbol, weight in projected_weights.items():
        thesis = thesis_map.get(symbol, "")
        if float(weight) > 1e-12 and thesis:
            counts[thesis] = counts.get(thesis, 0) + 1
    penalty = 0.0
    for thesis, count in counts.items():
        excess = max(int(count) - int(soft_max_names), 0)
        if not excess:
            continue
        thesis_profits = sorted(
            max(float(item.robust_net_profit_amount), 0.0)
            for item in selected
            if thesis_map.get(item.symbol, "") == thesis
            and item.exposure_delta > 0.0
        )
        penalty += 0.10 * sum(thesis_profits[:excess])
    return float(penalty)


def _projected_weights(
    selected: tuple[ActionProposal, ...],
    current_weights: Mapping[str, float],
) -> dict[str, float]:
    weights = {str(symbol): max(float(weight), 0.0) for symbol, weight in current_weights.items()}
    for item in selected:
        if item.action_type in {
            "exit",
            "hard_exit",
            "safety_exit",
            "replacement_sell",
        }:
            weights[item.symbol] = 0.0
        else:
            weights[item.symbol] = max(
                weights.get(item.symbol, 0.0) + float(item.exposure_delta),
                0.0,
            )
    return weights


def _portfolio_sigma(
    weights: Mapping[str, float],
    covariance_matrix: pd.DataFrame,
) -> float | None:
    """Daily portfolio volatility from a covariance matrix (not correlation)."""
    required_symbols = [
        symbol
        for symbol, weight in weights.items()
        if weight > 1e-12
    ]
    if not required_symbols:
        return 0.0
    if not _covariance_complete_for_weights(weights, covariance_matrix):
        return None
    symbols = required_symbols
    vector = pd.Series(
        [float(weights[symbol]) for symbol in symbols],
        index=symbols,
        dtype=float,
    )
    covariance = (
        covariance_matrix.loc[symbols, symbols]
        .apply(pd.to_numeric, errors="coerce")
    )
    if covariance.isna().any().any():
        return None
    variance = float(vector.T.dot(covariance).dot(vector))
    return max(variance, 0.0) ** 0.5


def _covariance_complete_for_weights(
    weights: Mapping[str, float],
    covariance_matrix: pd.DataFrame | None,
) -> bool:
    """Require 100% selected-symbol and pair coverage before covariance use."""
    if covariance_matrix is None or covariance_matrix.empty:
        return False
    symbols = [
        str(symbol)
        for symbol, weight in weights.items()
        if float(weight) > 1e-12
    ]
    if not symbols:
        return False
    if any(
        symbol not in covariance_matrix.index
        or symbol not in covariance_matrix.columns
        for symbol in symbols
    ):
        return False
    block = covariance_matrix.loc[symbols, symbols].apply(
        pd.to_numeric,
        errors="coerce",
    )
    if block.isna().any().any():
        return False
    values = block.to_numpy(dtype=float)
    return bool(
        math.isfinite(float(values.sum()))
        and (abs(values - values.T) <= 1e-10).all()
    )


def _marginal_covariance_risk_penalty(
    current_weights: Mapping[str, float],
    projected_weights: Mapping[str, float],
    *,
    covariance_matrix: pd.DataFrame | None,
    authorization: ExposureAuthorization,
    covariance_risk_aversion: float,
) -> float:
    """Convert daily covariance risk to the proposal forecast horizon in CNY."""
    if covariance_matrix is None or covariance_matrix.empty:
        return 0.0
    pre_sigma = _portfolio_sigma(current_weights, covariance_matrix)
    post_sigma = _portfolio_sigma(projected_weights, covariance_matrix)
    if pre_sigma is None or post_sigma is None:
        return 0.0
    horizon_scale = math.sqrt(max(int(authorization.risk_horizon_sessions), 1))
    return (
        max(post_sigma - pre_sigma, 0.0)
        * horizon_scale
        * float(authorization.nav_amount)
        * max(float(covariance_risk_aversion), 0.0)
    )


def _action_authorized(action_type: str, authorization: ExposureAuthorization) -> bool:
    action = str(action_type)
    if action == "new_entry":
        return authorization.new_entry_allowed
    if action in {"winner_pyramiding", "loser_averaging", "winner_add", "loser_add", "add"}:
        return authorization.add_allowed
    if action in {"replacement_buy", "replacement_sell"}:
        return authorization.replacement_allowed
    return True


def _is_buy_action(action_type: str) -> bool:
    return str(action_type) in {
        "new_entry",
        "winner_pyramiding",
        "loser_averaging",
        "winner_add",
        "loser_add",
        "add",
        "replacement_buy",
    }


def _pareto_reduce(
    proposals: tuple[ActionProposal, ...],
    *,
    limit: int,
) -> tuple[ActionProposal, ...]:
    if len(proposals) <= int(limit):
        return proposals
    ordered = sorted(
        proposals,
        key=lambda item: (
            -item.unit_capital_robust_return,
            item.primary_rank if item.primary_rank > 0.0 else float("inf"),
            -item.primary_score,
            -item.robust_net_profit_amount,
            item.downside_cvar_amount,
            item.proposal_id,
        ),
    )
    by_action: dict[str, ActionProposal] = {}
    by_symbol: dict[str, ActionProposal] = {}
    by_pool: dict[str, ActionProposal] = {}
    for item in ordered:
        by_action.setdefault(item.action_type, item)
        by_symbol.setdefault(item.symbol, item)
        if item.pool_id:
            by_pool.setdefault(item.pool_id, item)
    union = list(
        dict.fromkeys(
            [
                *by_action.values(),
                *by_pool.values(),
                *by_symbol.values(),
                *ordered,
            ]
        )
    )
    return tuple(union[: int(limit)])


def _rejection_reason(
    item: ActionProposal,
    authorization: ExposureAuthorization,
    selected_ids: set[str],
    *,
    reduced_ids: set[str],
    current_weights: Mapping[str, float],
    current_exposure: float,
    current_lots: Mapping[str, int],
    max_positions: int,
    thesis_map: Mapping[str, str],
    thesis_hard_max: int,
) -> str:
    if item.proposal_id in selected_ids:
        return ""
    if item.hard_veto_reasons:
        return "hard_veto:" + "|".join(item.hard_veto_reasons)
    if not _action_authorized(item.action_type, authorization):
        return "exposure_authorization"
    if item.action_type in {"exit", "discretionary_exit"} and (
        item.robust_net_profit_amount - item.authority_penalty_amount <= 0.0
    ):
        return "hold_dominates_discretionary_exit"
    if (
        item.robust_net_profit_amount
        - item.authority_penalty_amount
        <= 0.0
    ):
        return "non_positive_robust_profit"
    if item.proposal_id not in reduced_ids:
        return "pareto_reduced"
    if item.funding_cash_amount > max(
        float(authorization.current_cash_amount)
        - float(authorization.cash_buffer_amount),
        0.0,
    ) + 1e-8:
        return "cash_constraint"
    projected_weight = (
        float(current_weights.get(item.symbol, 0.0))
        + max(float(item.exposure_delta), 0.0)
    )
    if projected_weight > authorization.per_name_structural_cap + 1e-12:
        return "per_name_structural_cap"
    if (
        float(current_exposure) + float(item.exposure_delta)
        > authorization.risk_exposure_ceiling + 1e-12
    ):
        return "exposure_ceiling"
    if item.downside_cvar_amount > authorization.portfolio_stress_budget_amount:
        return "portfolio_stress_budget"
    if (
        item.action_type == "new_entry"
        and item.symbol not in current_lots
        and sum(1 for lots in current_lots.values() if lots > 0)
        >= int(max_positions)
    ):
        return "position_slot_limit"
    thesis = thesis_map.get(item.symbol, "")
    if thesis and item.exposure_delta > 0.0:
        baseline = sum(
            1
            for symbol, weight in current_weights.items()
            if weight > 1e-12 and thesis_map.get(symbol, "") == thesis
        )
        projected = baseline + (0 if item.symbol in current_weights else 1)
        if projected > int(thesis_hard_max) and projected > baseline:
            return "thesis_hard_cap_non_worsening"
    if any(
        proposal_id in selected_ids
        for proposal_id in selected_ids
        if f"|{item.symbol}|" in proposal_id
    ):
        return "alternative_lot_not_selected"
    return "dominated_or_portfolio_constraint"


def _empty_plan(
    authorization: ExposureAuthorization,
    *,
    current_lots: Mapping[str, int],
    current_weights: Mapping[str, float],
    current_exposure: float,
    max_positions: int,
    minimum_positions: int = 0,
    minimum_exposure: float = 0.0,
    target_positions: int = 0,
    target_exposure: float = 0.0,
    wealth_materiality_epsilon_amount: float = 0.0,
    minimum_active_pool_size: int = 0,
    minimum_effective_n_ratio: float = 0.0,
    minimum_pool_count: int = 0,
) -> ActionPlan:
    """Return the factual no-action portfolio, not a synthetic zero account."""
    projected_exposure = (
        min(sum(max(float(weight), 0.0) for weight in current_weights.values()), 1.0)
        if current_weights
        else min(max(float(current_exposure), 0.0), 1.0)
    )
    projected_cash = max(float(authorization.current_cash_amount), 0.0)
    planned_holding_count = sum(int(lots) > 0 for lots in current_lots.values())
    holding_floor_violation = max(
        int(minimum_positions) - planned_holding_count,
        0,
    )
    exposure_floor_violation = max(
        float(minimum_exposure) - projected_exposure,
        0.0,
    )
    return ActionPlan(
        decision_id=authorization.decision_id,
        selected_proposal_ids=(),
        rejected_proposals=(),
        target_lots_by_symbol=dict(current_lots),
        expected_net_profit_amount=0.0,
        robust_net_profit_amount=0.0,
        downside_cvar_amount=0.0,
        exact_cost_amount=0.0,
        projected_cash=projected_cash,
        projected_exposure=projected_exposure,
        projected_stress_loss=0.0,
        objective_lexicographic_rank=(0.0, 0.0, 0.0, 0.0),
        constraint_slacks={
            "exposure": max(
                authorization.risk_exposure_ceiling - projected_exposure,
                0.0,
            ),
            "stress": authorization.portfolio_stress_budget_amount,
            "cash": max(
                projected_cash - authorization.cash_buffer_amount,
                0.0,
            ),
            "holding_floor_violation_count": holding_floor_violation,
            "exposure_floor_violation": exposure_floor_violation,
            "atomic_pool_violation_count": (
                max(int(minimum_active_pool_size) - planned_holding_count, 0)
                if 0 < planned_holding_count < int(minimum_active_pool_size)
                else 0
            ),
            "minimum_effective_n_ratio": max(
                min(float(minimum_effective_n_ratio), 1.0), 0.0
            ),
            "minimum_pool_count": max(int(minimum_pool_count), 0),
            "best_feasible_buy_robust_objective": 0.0,
            "best_feasible_nonbuy_robust_objective": 0.0,
            "buy_plan_dominates_nonbuy": 0,
        },
        solver_status="empty",
        plan_id=f"{authorization.decision_id}|action_plan",
        optimizer_invocation_count=1,
        deployment_gap=max(
            float(authorization.effective_deployment_target)
            - projected_exposure,
            0.0,
        ),
        breadth_score=_normalized_breadth_score(
            current_weights,
            (),
            max_positions=max(int(max_positions), 1),
        ),
        authority_penalty_amount=0.0,
        concentration_penalty_amount=_concentration_penalty(
            current_weights,
            authorization,
        ),
        marginal_risk_penalty_amount=0.0,
        proposal_robust_profit_amount=0.0,
        thesis_penalty_amount=0.0,
        deployment_penalty_amount=0.0,
        risk_model_used=str(authorization.fallback_risk_model),
        risk_horizon_sessions=int(authorization.risk_horizon_sessions),
        risk_episode_id=str(authorization.risk_episode_id),
        planned_holding_count=planned_holding_count,
        holding_floor_violation_count=holding_floor_violation,
        exposure_floor_violation=exposure_floor_violation,
        wealth_materiality_epsilon_amount=max(
            float(wealth_materiality_epsilon_amount),
            0.0,
        ),
        objective_components={
            "holding_floor_violation_count": float(holding_floor_violation),
            "exposure_floor_violation": float(exposure_floor_violation),
            "robust_wealth_amount": 0.0,
            "target_holding_gap": float(
                abs(int(target_positions) - planned_holding_count)
            ),
            "target_exposure_gap": float(
                abs(float(target_exposure) - projected_exposure)
            ),
        },
    )
