"""Unique integer action optimizer for SCAP-V2.

The optimizer is deliberately small-capital specific: with at most five live
names, an exhaustive bounded search is deterministic, auditable, and avoids
the unit drift caused by continuous weights followed by lot rounding.
"""
from __future__ import annotations

from itertools import combinations
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
    correlation_penalty_rate: float = 0.10,
) -> ActionPlan:
    """Return the sole strategy-authorized integer ActionPlan.

    Hard-vetoed proposals are rejected before search.  Safety exits may be
    represented with ``action_type='safety_exit'`` and are always included;
    all other actions compete on robust net profit.  The first objective is
    robust CNY profit, followed by lower downside/cost, then higher residual
    cash. Spending more is never a tie-break objective.
    """
    items = tuple(proposals)
    if not items:
        return _empty_plan(authorization)
    if any(item.decision_id != authorization.decision_id for item in items):
        raise ValueError("all proposals and authorization must share decision_id")
    if len({item.proposal_id for item in items}) != len(items):
        raise ValueError("proposal_id must be unique")

    current_lots = {
        str(symbol): max(int(lots), 0)
        for symbol, lots in (current_lots_by_symbol or {}).items()
    }
    current_weights = {
        str(symbol): max(float(weight), 0.0)
        for symbol, weight in (current_weights_by_symbol or {}).items()
    }
    thesis_map = {str(k): str(v) for k, v in (thesis_by_symbol or {}).items()}
    forced = tuple(
        item
        for item in items
        if item.executable and item.action_type in {"safety_exit", "hard_exit"}
    )
    candidates = tuple(
        item
        for item in items
        if item.executable
        and item not in forced
        and item.robust_net_profit_amount > 0.0
        and _action_authorized(item.action_type, authorization)
    )
    # A bounded reducer keeps exhaustive enumeration predictable while
    # preserving diverse actions/symbols.
    candidates = _pareto_reduce(candidates, limit=20)
    pair_expected_counts: dict[str, int] = {}
    for item in items:
        if item.replacement_pair_id:
            pair_expected_counts[item.replacement_pair_id] = (
                pair_expected_counts.get(item.replacement_pair_id, 0) + 1
            )

    best = forced
    best_key = _plan_key(
        forced,
        authorization=authorization,
        current_lots=current_lots,
        current_weights=current_weights,
        current_exposure=current_exposure,
        max_positions=max_positions,
        thesis_map=thesis_map,
        max_names_per_thesis=max_names_per_thesis,
        pair_expected_counts=pair_expected_counts,
        correlation_matrix=correlation_matrix,
        correlation_penalty_rate=correlation_penalty_rate,
    )
    max_optional = min(max(int(max_positions), 0), len(candidates))
    for size in range(1, max_optional + 1):
        for optional in combinations(candidates, size):
            selected = forced + optional
            key = _plan_key(
                selected,
                authorization=authorization,
                current_lots=current_lots,
                current_weights=current_weights,
                current_exposure=current_exposure,
                max_positions=max_positions,
                thesis_map=thesis_map,
                max_names_per_thesis=max_names_per_thesis,
                pair_expected_counts=pair_expected_counts,
                correlation_matrix=correlation_matrix,
                correlation_penalty_rate=correlation_penalty_rate,
            )
            if key is None:
                continue
            if best_key is None or key > best_key:
                best, best_key = selected, key

    selected_ids = {item.proposal_id for item in best}
    rejected = tuple(
        {
            "proposal_id": item.proposal_id,
            "symbol": item.symbol,
            "action_type": item.action_type,
            "reason": _rejection_reason(item, authorization, selected_ids),
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
    projected_cash = max(available_cash - funding, 0.0)
    projected_weights = _projected_weights(best, current_weights)
    projected_exposure = (
        min(sum(projected_weights.values()), 1.0)
        if current_weights
        else min(current_exposure + funding / authorization.nav_amount, 1.0)
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
        objective_lexicographic_rank=(robust, -downside, -cost, projected_cash),
        constraint_slacks={
            "exposure": max(
                authorization.risk_exposure_ceiling - projected_exposure, 0.0
            ),
            "stress": max(
                authorization.portfolio_stress_budget_amount - downside, 0.0
            ),
        },
        solver_status="optimal_bounded_exhaustive",
        plan_id=f"{authorization.decision_id}|action_plan",
        optimizer_invocation_count=1,
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
    correlation_matrix: pd.DataFrame | None,
    correlation_penalty_rate: float,
) -> tuple[float, float, float, float, tuple[str, ...]] | None:
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
    downside = 0.0
    for item in selected:
        if item.action_type in {"exit", "hard_exit", "safety_exit", "replacement_sell"}:
            symbols.discard(item.symbol)
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
    if funding > max(available_cash - required_buffer, 0.0) + 1e-8:
        return None
    if downside > authorization.portfolio_stress_budget_amount + 1e-12:
        return None
    if thesis_map:
        counts: dict[str, int] = {}
        for symbol in symbols:
            thesis = thesis_map.get(symbol, "")
            if not thesis:
                continue
            counts[thesis] = counts.get(thesis, 0) + 1
        if any(count > int(max_names_per_thesis) for count in counts.values()):
            return None

    robust = sum(item.robust_net_profit_amount for item in selected)
    if correlation_matrix is not None and not correlation_matrix.empty:
        buy_items = [
            item
            for item in selected
            if item.action_type
            not in {"exit", "hard_exit", "safety_exit", "replacement_sell"}
        ]
        interaction_penalty = 0.0
        for left_index, left in enumerate(buy_items):
            for right in buy_items[left_index + 1 :]:
                if (
                    left.symbol in correlation_matrix.index
                    and right.symbol in correlation_matrix.columns
                ):
                    corr = pd.to_numeric(
                        pd.Series(
                            [correlation_matrix.at[left.symbol, right.symbol]]
                        ),
                        errors="coerce",
                    ).iloc[0]
                    if pd.notna(corr):
                        interaction_penalty += (
                            max(float(corr), 0.0)
                            * max(float(correlation_penalty_rate), 0.0)
                            * min(
                                max(left.robust_net_profit_amount, 0.0),
                                max(right.robust_net_profit_amount, 0.0),
                            )
                        )
        robust -= interaction_penalty
    expected = sum(item.expected_net_profit_amount for item in selected)
    cost = sum(item.exact_cost_amount for item in selected)
    residual = max(
        authorization.nav_amount
        * max(authorization.risk_exposure_ceiling - float(current_exposure), 0.0)
        - funding,
        0.0,
    )
    ids = tuple(sorted(item.proposal_id for item in selected))
    return robust, expected, -downside, -cost, ids


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


def _action_authorized(action_type: str, authorization: ExposureAuthorization) -> bool:
    action = str(action_type)
    if action == "new_entry":
        return authorization.new_entry_allowed
    if action in {"winner_pyramiding", "loser_averaging", "winner_add", "loser_add", "add"}:
        return authorization.add_allowed
    if action in {"replacement_buy", "replacement_sell"}:
        return authorization.replacement_allowed
    return True


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
            -item.robust_net_profit_amount,
            -(item.robust_net_profit_amount / max(item.funding_cash_amount, 1.0)),
            item.downside_cvar_amount,
            item.proposal_id,
        ),
    )
    by_action: dict[str, ActionProposal] = {}
    by_symbol: dict[str, ActionProposal] = {}
    for item in ordered:
        by_action.setdefault(item.action_type, item)
        by_symbol.setdefault(item.symbol, item)
    union = list(dict.fromkeys([*by_action.values(), *by_symbol.values(), *ordered]))
    return tuple(union[: int(limit)])


def _rejection_reason(
    item: ActionProposal,
    authorization: ExposureAuthorization,
    selected_ids: set[str],
) -> str:
    if item.proposal_id in selected_ids:
        return ""
    if item.hard_veto_reasons:
        return "hard_veto:" + "|".join(item.hard_veto_reasons)
    if not _action_authorized(item.action_type, authorization):
        return "exposure_authorization"
    if item.robust_net_profit_amount <= 0.0:
        return "non_positive_robust_profit"
    return "dominated_or_portfolio_constraint"


def _empty_plan(authorization: ExposureAuthorization) -> ActionPlan:
    return ActionPlan(
        decision_id=authorization.decision_id,
        selected_proposal_ids=(),
        rejected_proposals=(),
        target_lots_by_symbol={},
        expected_net_profit_amount=0.0,
        robust_net_profit_amount=0.0,
        downside_cvar_amount=0.0,
        exact_cost_amount=0.0,
        projected_cash=authorization.nav_amount
        * authorization.risk_exposure_ceiling,
        projected_exposure=0.0,
        projected_stress_loss=0.0,
        objective_lexicographic_rank=(0.0, 0.0, 0.0, 0.0),
        constraint_slacks={
            "exposure": authorization.risk_exposure_ceiling,
            "stress": authorization.portfolio_stress_budget_amount,
        },
        solver_status="empty",
        plan_id=f"{authorization.decision_id}|action_plan",
        optimizer_invocation_count=1,
    )
