"""Unique integer action optimizer for SCAP-V2.

The optimizer is deliberately small-capital specific: with at most five live
names, an exhaustive bounded search is deterministic, auditable, and avoids
the unit drift caused by continuous weights followed by lot rounding.
"""
from __future__ import annotations

from itertools import combinations
import math
from typing import Iterable, Mapping

import pandas as pd

from functions.decision_council.scap_v2_contracts import (
    ActionPlan,
    ActionProposal,
    ExposureAuthorization,
)


def optimize_action_proposals(
    proposals: Iterable[ActionProposal],
    *,
    authorization: ExposureAuthorization,
    current_lots_by_symbol: Mapping[str, int] | None = None,
    current_weights_by_symbol: Mapping[str, float] | None = None,
    current_exposure: float = 0.0,
    max_positions: int = 5,
    thesis_by_symbol: Mapping[str, str] | None = None,
    max_names_per_thesis: int = 2,
    correlation_matrix: pd.DataFrame | None = None,
    covariance_matrix: pd.DataFrame | None = None,
    covariance_risk_aversion: float = 0.05,
    candidate_limit: int = 24,
    exhaustive_max_positions: int = 8,
    beam_width: int = 512,
) -> ActionPlan:
    """Return the sole strategy-authorized integer ActionPlan.

    Hard-vetoed proposals are rejected before search.  Safety exits may be
    represented with ``action_type='safety_exit'`` and are always included;
    all other actions compete on robust net profit.  The first objective is
    robust CNY profit, followed by lower downside/cost, then higher residual
    cash. Spending more is never a tie-break objective.
    """
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
        limit=max(int(candidate_limit), int(max_positions)),
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
            covariance_risk_aversion=covariance_risk_aversion,
        )

    best = forced
    best_key = evaluate(forced)
    best_nonbuy_key = best_key
    best_buy_key = None
    exact_solver = bool(
        int(max_positions) <= max(int(exhaustive_max_positions), 1)
        and len(candidates) <= 24
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
                elif best_nonbuy_key is None or key > best_nonbuy_key:
                    best_nonbuy_key = key
                if best_key is None or key > best_key:
                    best, best_key = selected, key
        solver_status = "optimal_bounded_exhaustive"
    else:
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
            elif best_nonbuy_key is None or key > best_nonbuy_key:
                best_nonbuy_key = key
            if best_key is None or key > best_key:
                best, best_key = selected, key
        solver_status = "feasible_bounded_beam_search"

    selected_ids = {item.proposal_id for item in best}
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
    robust = float(best_key[0]) if best_key is not None else 0.0
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
        else min(current_exposure + funding / authorization.nav_amount, 1.0)
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
    authority_penalty = sum(
        max(float(item.authority_penalty_amount), 0.0)
        for item in best
    )
    concentration_penalty = _concentration_penalty(
        projected_weights,
        authorization,
    )
    marginal_risk_penalty = _marginal_covariance_risk_penalty(
        current_weights,
        projected_weights,
        covariance_matrix=effective_covariance,
        authorization=authorization,
        covariance_risk_aversion=covariance_risk_aversion,
    )
    buy_plan_dominates_nonbuy = bool(
        best_buy_key is not None
        and (best_nonbuy_key is None or best_buy_key > best_nonbuy_key)
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
            "best_feasible_buy_robust_objective": (
                float(best_buy_key[0]) if best_buy_key is not None else 0.0
            ),
            "best_feasible_nonbuy_robust_objective": (
                float(best_nonbuy_key[0])
                if best_nonbuy_key is not None
                else 0.0
            ),
            "buy_plan_dominates_nonbuy": int(buy_plan_dominates_nonbuy),
            "deployment_gap": deployment_gap,
            "breadth_score": breadth_score,
            "authority_penalty_amount": authority_penalty,
            "concentration_penalty_amount": concentration_penalty,
            "marginal_risk_penalty_amount": marginal_risk_penalty,
            "cash_release_amount": cash_release,
            "solver_candidate_count": len(candidates),
            "solver_beam_width": (
                0 if exact_solver else max(int(beam_width), 1)
            ),
            "solver_optimality_proven": int(exact_solver),
        },
        solver_status=solver_status,
        plan_id=f"{authorization.decision_id}|action_plan",
        optimizer_invocation_count=1,
        deployment_gap=deployment_gap,
        breadth_score=breadth_score,
        authority_penalty_amount=authority_penalty,
        concentration_penalty_amount=concentration_penalty,
        marginal_risk_penalty_amount=marginal_risk_penalty,
        risk_model_used=(
            "covariance"
            if effective_covariance is not None
            and not effective_covariance.empty
            else str(authorization.fallback_risk_model)
        ),
        risk_horizon_sessions=int(authorization.risk_horizon_sessions),
        risk_episode_id=str(authorization.risk_episode_id),
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
    covariance_risk_aversion: float,
) -> tuple[float, float, float, float, float, float, tuple[str, ...]] | None:
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
        projected_exposure = float(current_exposure) + funding / authorization.nav_amount
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
    if downside > authorization.portfolio_stress_budget_amount + 1e-12:
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

    robust = sum(
        item.robust_net_profit_amount - item.authority_penalty_amount
        for item in selected
    )
    soft_thesis_penalty = 0.0
    if thesis_map:
        for thesis, count in counts.items():
            excess = max(count - int(authorization.thesis_soft_max_names), 0)
            if excess:
                thesis_profits = sorted(
                    (
                        max(item.robust_net_profit_amount, 0.0)
                        for item in selected
                        if thesis_map.get(item.symbol, "") == thesis
                        and item.exposure_delta > 0.0
                    )
                )
                soft_thesis_penalty += 0.10 * sum(thesis_profits[:excess])
    robust -= soft_thesis_penalty
    robust -= _marginal_covariance_risk_penalty(
        current_weights,
        projected_weights,
        covariance_matrix=covariance_matrix,
        authorization=authorization,
        covariance_risk_aversion=covariance_risk_aversion,
    )
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
    robust -= (
        authorization.nav_amount
        * authorization.cash_gap_penalty_rate
        * deployment_gap
    )
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
    return robust, -deployment_gap, breadth, expected, -downside, -cost, ids


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
) -> float:
    """Daily portfolio volatility from a covariance matrix (not correlation)."""
    symbols = [
        symbol
        for symbol, weight in weights.items()
        if weight > 1e-12
        and symbol in covariance_matrix.index
        and symbol in covariance_matrix.columns
    ]
    if not symbols:
        return 0.0
    vector = pd.Series(
        [float(weights[symbol]) for symbol in symbols],
        index=symbols,
        dtype=float,
    )
    covariance = (
        covariance_matrix.loc[symbols, symbols]
        .apply(pd.to_numeric, errors="coerce")
        .fillna(0.0)
    )
    variance = float(vector.T.dot(covariance).dot(vector))
    return max(variance, 0.0) ** 0.5


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
) -> ActionPlan:
    """Return the factual no-action portfolio, not a synthetic zero account."""
    projected_exposure = (
        min(sum(max(float(weight), 0.0) for weight in current_weights.values()), 1.0)
        if current_weights
        else min(max(float(current_exposure), 0.0), 1.0)
    )
    projected_cash = max(float(authorization.current_cash_amount), 0.0)
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
        breadth_score=float(
            min(
                sum(
                    1
                    for weight in current_weights.values()
                    if float(weight) > 1e-12
                ),
                4,
            )
        ),
        authority_penalty_amount=0.0,
        concentration_penalty_amount=_concentration_penalty(
            current_weights,
            authorization,
        ),
        marginal_risk_penalty_amount=0.0,
        risk_model_used=str(authorization.fallback_risk_model),
        risk_horizon_sessions=int(authorization.risk_horizon_sessions),
        risk_episode_id=str(authorization.risk_episode_id),
    )
