"""SCAP-V3 Lean proposal factory and single-plan orchestration.

This module owns no execution or accounting state.  It converts factual
candidate/position snapshots into comparable integer-lot proposals and calls
the sole optimizer exactly once.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import pandas as pd

from functions.decision_council.action_utility import round_trip_cost_amount
from functions.decision_council.capital_scaling import scaled_candidate_budgets
from functions.execution.security_trading_rules import trading_rule_for
from functions.decision_council.integer_action_optimizer import (
    optimize_action_proposals,
)
from functions.decision_council.scap_v2_contracts import (
    ActionPlan,
    ActionProposal,
    ExposureAuthorization,
)
from functions.decision_council.scap_v31_authority import (
    attach_scap_v31_authority,
)


LEAN_VERSION = "small_capital_aggressive_profit_v3_2"
LEAN_PROPOSAL_CONTRACT = "scap_v32_pool_preserving_proposal_factory_v1"


@dataclass(frozen=True)
class LeanDecision:
    proposals: tuple[ActionProposal, ...]
    plan: ActionPlan
    authorization: ExposureAuthorization
    proposal_rows: dict[str, pd.Series]
    diagnostics: dict


def build_lean_decision(context, candidates: pd.DataFrame) -> LeanDecision:
    """Build all actions first, then invoke the integer optimizer once."""
    authority_columns = {
        "scap_v31_authority_tier",
        "scap_v31_decision_expected_return",
        "scap_v31_max_lots",
    }
    if authority_columns.issubset(candidates.columns):
        data = candidates.copy()
    else:
        # Direct callers and contract tests may not have executed the runner's
        # daily authority stage. Compute it once here as a fail-closed fallback.
        data = attach_scap_v31_authority(
            candidates,
            horizon_days=max(int(context.forecast_horizon_sessions), 1),
            position_cap_mode=str(
                (context.execution_cost_profile or {}).get(
                    "position_cap_mode",
                    "fixed",
                )
            ),
            target_position_cash=(
                float(context.safety.exposure_cap)
                * float(context.nav_amount)
                / max(int(context.top_n), 1)
            ),
            authority_snapshot_id=f"{context.decision_id}|authority",
        )
    if "scap_authority_snapshot_id" not in data.columns:
        data["scap_authority_snapshot_id"] = f"{context.decision_id}|authority"
    data["symbol"] = data["symbol"].astype(str)
    data = _attach_pool_contract(data)
    rows = _deduplicate_pool_rows(data)
    profile = dict(context.execution_cost_profile or {})
    current_weights = {
        str(symbol): max(float(weight), 0.0)
        for symbol, weight in context.current_weights.items()
    }
    proposals: list[ActionProposal] = []
    proposal_rows: dict[str, pd.Series] = {}
    current_lots: dict[str, int] = {}
    positive_signal_weights: list[float] = []
    raw_entry_signal_symbols: set[str] = set()
    structural_entry_symbols: set[str] = set()
    proposal_entry_symbols: set[str] = set()

    for symbol, row in rows.items():
        old_weight = current_weights.get(symbol, 0.0)
        lot_cash = _number(row.get("mainline_v3_one_lot_cash_required"))
        lot_weight = _number(row.get("mainline_v3_one_lot_weight"))
        if lot_weight <= 0.0 and lot_cash > 0.0:
            lot_weight = lot_cash / max(float(context.nav_amount), 1e-12)
        if lot_cash <= 0.0 and lot_weight > 0.0:
            lot_cash = lot_weight * float(context.nav_amount)
        exact_current_lots = dict(
            getattr(context, "current_lots_by_symbol", None) or {}
        )
        if old_weight > 0.0:
            if symbol in exact_current_lots:
                current_lots[symbol] = max(
                    int(exact_current_lots[symbol]),
                    1,
                )
            elif lot_weight > 0.0:
                current_lots[symbol] = max(
                    int(round(old_weight / lot_weight)),
                    1,
                )

        if old_weight > 0.0:
            _append_held_proposals(
                proposals,
                proposal_rows,
                context=context,
                symbol=symbol,
                row=row,
                old_weight=old_weight,
                lot_cash=lot_cash,
                lot_weight=lot_weight,
            )
            continue

        utility = _number(row.get("scap_candidate_utility"))
        authority_tier = str(row.get("scap_v31_authority_tier", "D") or "D")
        decision_return = _number(row.get("scap_v31_decision_expected_return"))
        point_return = _number(
            row.get("scap_expected_return_point", decision_return)
        )
        hard_vetoes = _entry_hard_vetoes(
            row,
            lot_cash,
            lot_weight,
            structural_cap=float(context.per_name_structural_cap),
        )
        if decision_return <= 0.0 and utility <= 0.0:
            continue
        raw_entry_signal_symbols.add(symbol)
        if hard_vetoes:
            continue
        structural_entry_symbols.add(symbol)
        max_by_name = int(
            math.floor(max(float(context.per_name_structural_cap), 0.0) / lot_weight)
        ) if lot_weight > 0.0 else 0
        max_by_cash = int(
            math.floor(
                max(float(context.cash_amount) - float(context.cash_buffer_amount), 0.0)
                / lot_cash
            )
        ) if lot_cash > 0.0 else 0
        max_lots = min(
            max(max_by_name, 0),
            max(max_by_cash, 0),
            int(_number(row.get("scap_v31_max_lots"), 0.0)),
        )
        if max_lots > 0:
            proposal_entry_symbols.add(symbol)
        symbol_has_positive_plan = False
        for lots in range(1, max_lots + 1):
            minimum_quantity = max(
                int(_number(row.get("mainline_v3_minimum_buy_quantity"), 100.0)),
                1,
            )
            price = lot_cash / minimum_quantity
            exact_cost = round_trip_cost_amount(
                symbol=symbol,
                price=price,
                shares=float(minimum_quantity * lots),
                trade_date=context.decision_date,
                cost_profile=context.execution_cost_profile,
            )
            concentration_penalty = max(
                lots * lot_weight - 0.30, 0.0
            ) * float(context.nav_amount) * 0.01
            risk_penalty = _number(row.get("scap_risk_penalty_amount")) * lots
            authority_penalty_rate = max(
                float(
                    profile.get(
                        {
                            "A": "scap_tier_a_uncertainty_rate",
                            "B": "scap_tier_b_uncertainty_rate",
                            "C": "scap_tier_c_uncertainty_rate",
                        }.get(authority_tier, "scap_tier_c_uncertainty_rate"),
                        {
                            "A": 0.0,
                            "B": 0.0005,
                            "C": 0.0010,
                        }.get(authority_tier, 0.0010),
                    )
                    or 0.0
                ),
                0.0,
            )
            authority_penalty = lot_cash * lots * authority_penalty_rate
            if decision_return > 0.0:
                expected_profit = (
                    point_return * lot_cash * lots - exact_cost
                )
                robust_profit = (
                    decision_return * lot_cash * lots
                    - exact_cost
                    - risk_penalty
                    - concentration_penalty
                )
            else:
                # Compatibility for already-net synthetic/legacy proposals.
                expected_profit = utility * lots
                robust_profit = utility * lots - concentration_penalty
            proposal = _proposal(
                context,
                symbol=symbol,
                action_type="new_entry",
                lots=lots,
                expected=expected_profit,
                robust=robust_profit,
                downside=lot_cash * lots * 0.15,
                cost=exact_cost,
                funding=lot_cash * lots,
                suffix=f"entry_{lots}lot",
                source="mainline_v3_score_contract",
                authority_tier=authority_tier,
                thesis=str(row.get("cabinet_entry_thesis", "") or ""),
                pool_id=str(row.get("scap_v32_pool_id", "") or ""),
                pool_memberships=tuple(
                    token
                    for token in str(
                        row.get("scap_v32_pool_memberships", "")
                    ).split("|")
                    if token
                ),
                primary_score=_number(
                    row.get(
                        "primary_score",
                        row.get("cabinet_native_final_score", 0.0),
                    )
                ),
                primary_rank=_number(row.get("scap_v32_pool_rank"), 0.0),
                unit_capital_robust_return=(
                    (robust_profit - authority_penalty)
                    / max(lot_cash * lots, 1.0)
                ),
                authority_penalty_amount=authority_penalty,
            )
            proposals.append(proposal)
            proposal_rows[proposal.proposal_id] = row
            symbol_has_positive_plan = (
                symbol_has_positive_plan or robust_profit > 0.0
            )
        if symbol_has_positive_plan:
            positive_signal_weights.append(lot_weight)

    current_exposure = min(sum(current_weights.values()), 1.0)
    strategic_budget = min(
        max(
            float(
                context.desired_exposure_target
                if context.desired_exposure_target is not None
                else context.safety.exposure_cap
            ),
            0.0,
        ),
        1.0,
    )
    hard_exposure_ceiling = min(
        max(
            float(
                context.hard_exposure_ceiling
                if context.hard_exposure_ceiling is not None
                else context.safety.exposure_cap
            ),
            0.0,
        ),
        1.0,
    )
    confirmed_derisk_target = (
        min(max(float(context.confirmed_derisk_target), 0.0), 1.0)
        if context.confirmed_derisk_target is not None
        else None
    )
    planned_safety_sell_weight = _append_exposure_cap_safety_exits(
        proposals,
        proposal_rows,
        context=context,
        rows=rows,
        current_weights=current_weights,
        current_lots=current_lots,
        current_exposure=current_exposure,
        strategic_budget=(
            confirmed_derisk_target
            if confirmed_derisk_target is not None
            else hard_exposure_ceiling
        ),
        derisk_confirmed=confirmed_derisk_target is not None,
    )
    signal_supported = min(
        current_exposure + sum(sorted(positive_signal_weights)[: max(int(context.top_n), 0)]),
        strategic_budget,
    )
    spendable = max(float(context.cash_amount) - float(context.cash_buffer_amount), 0.0)
    affordable_weights = [
        weight
        for weight in sorted(positive_signal_weights)
        if weight * float(context.nav_amount) <= spendable + 1e-8
    ]
    integer_feasible = min(
        current_exposure + sum(affordable_weights[: max(int(context.top_n), 0)]),
        signal_supported,
    )
    covariance = context.covariance_matrix
    covariance_state = (
        "shrunk_covariance_70_30"
        if covariance is not None and not covariance.empty
        else "fallback_thesis_caps"
    )
    current_tier_b_exposure = sum(
        current_weights.get(symbol, 0.0)
        for symbol, row in rows.items()
        if str(row.get("entry_authority_tier", "") or "") == "B"
    )
    current_exploration_exposure = sum(
        current_weights.get(symbol, 0.0)
        for symbol, row in rows.items()
        if str(row.get("entry_authority_tier", "") or "") in {"B", "C"}
    )
    current_tier_c_names = sum(
        current_weights.get(symbol, 0.0) > 0.0
        and str(row.get("entry_authority_tier", "") or "") == "C"
        for symbol, row in rows.items()
    )
    configured_c_max = max(
        int(profile.get("scap_tier_c_max_names", context.top_n) or context.top_n),
        0,
    )
    configured_exploration_cap = min(
        max(float(profile.get("scap_exploration_exposure_cap", 1.0) or 1.0), 0.0),
        1.0,
    )
    risk_level = str(context.safety.risk_level).strip().lower()
    trigger_streak = max(int(context.safety.trigger_streak_days), 0)
    risk_episode_active = bool(
        risk_level == "high"
        or (
            risk_level != "normal"
            and str(context.safety.trigger_source).strip().lower()
            not in {"", "normal"}
            and trigger_streak > 0
        )
    )
    episode_start = pd.Timestamp(context.decision_date) - pd.offsets.BDay(
        max(trigger_streak - 1, 0)
    )
    risk_episode_id = (
        f"{pd.Timestamp(episode_start).strftime('%Y%m%d')}|"
        f"{risk_level}|{str(context.safety.trigger_source)}"
        if risk_episode_active
        else ""
    )
    authorization = ExposureAuthorization(
        decision_id=str(context.decision_id),
        nav_amount=max(float(context.nav_amount), 1e-12),
        risk_exposure_ceiling=hard_exposure_ceiling,
        cash_buffer_amount=max(float(context.cash_buffer_amount), 0.0),
        per_name_structural_cap=min(
            max(float(context.per_name_structural_cap), 0.0), 1.0
        ),
        per_name_stress_budget_amount=float(context.nav_amount)
        * float(context.per_name_structural_cap)
        * 0.40,
        portfolio_stress_budget_amount=max(
            float(context.portfolio_stress_budget_amount), 0.0
        ),
        new_entry_allowed=(
            not bool(context.safety.hard_freeze_active)
            and planned_safety_sell_weight <= 1e-12
            and not risk_episode_active
            and current_exposure < strategic_budget - 1e-12
            and not (
                bool(profile.get("scap_block_new_entry_during_high_risk", True))
                and risk_level == "high"
            )
        ),
        add_allowed=(
            not bool(context.safety.hard_freeze_active)
            and current_exposure < strategic_budget - 1e-12
        ),
        replacement_allowed=bool(context.active_replacement_enabled),
        current_cash_amount=max(float(context.cash_amount), 0.0),
        strategic_exposure_budget=strategic_budget,
        signal_supported_exposure=signal_supported,
        integer_feasible_exposure=integer_feasible,
        covariance_state=covariance_state,
        fallback_risk_model="thesis_and_per_name_stress_caps",
        tier_b_exposure_cap=1.0,
        tier_c_max_names=max(configured_c_max - current_tier_c_names, 0),
        exploration_exposure_cap=max(
            configured_exploration_cap - current_exploration_exposure,
            0.0,
        ),
        desired_exposure_target=strategic_budget,
        effective_deployment_target=min(
            strategic_budget,
            signal_supported,
            integer_feasible,
        ),
        per_name_soft_cap=min(
            max(
                float(profile.get("scap_single_position_soft_cap", 0.25) or 0.25),
                0.0,
            ),
            float(context.per_name_structural_cap),
        ),
        cash_gap_penalty_rate=max(
            float(profile.get("scap_cash_gap_penalty_rate", 0.0) or 0.0),
            0.0,
        ),
        name_concentration_penalty_rate=max(
            float(
                profile.get(
                    "scap_name_concentration_penalty_rate",
                    0.0,
                )
                or 0.0
            ),
            0.0,
        ),
        breadth_near_optimal_tolerance_amount=max(
            float(
                profile.get(
                    "scap_breadth_near_optimal_tolerance_rate",
                    0.0,
                )
                or 0.0
            )
            * float(context.nav_amount),
            0.0,
        ),
        risk_episode_id=risk_episode_id,
        risk_reentry_blocked=bool(
            risk_episode_active or planned_safety_sell_weight > 1e-12
        ),
        hard_exposure_ceiling=hard_exposure_ceiling,
        confirmed_derisk_target=confirmed_derisk_target,
        authority_snapshot_id=f"{context.decision_id}|authority",
        risk_horizon_sessions=max(
            int(context.forecast_horizon_sessions),
            1,
        ),
    )
    pool_count = max(
        len(
            {
                str(row.get("cabinet_entry_thesis", "") or "")
                for row in rows.values()
                if str(row.get("cabinet_entry_thesis", "") or "")
            }
        ),
        1,
    )
    scalable_budgets = scaled_candidate_budgets(
        effective_position_cap=max(int(context.top_n), 1),
        pool_count=pool_count,
        optimizer_multiple=float(
            profile.get("scap_optimizer_candidate_multiple", 4.0) or 4.0
        ),
        search_cap=int(
            profile.get("scap_optimizer_candidate_search_cap", 96) or 96
        ),
    )
    fixed_mode = str(profile.get("position_cap_mode", "fixed")).lower() == "fixed"
    thesis_hard_max = (
        3
        if fixed_mode
        else scalable_budgets["thesis_hard_max_names"]
    )
    optimizer_candidate_limit = (
        max(int(profile.get("scap_optimizer_candidate_limit", 24) or 24), 5)
        if fixed_mode
        else scalable_budgets["optimizer_candidate_limit"]
    )
    plan = optimize_action_proposals(
        proposals,
        authorization=authorization,
        current_lots_by_symbol=current_lots,
        current_weights_by_symbol=current_weights,
        current_exposure=current_exposure,
        max_positions=max(int(context.top_n), 1),
        thesis_by_symbol={
            symbol: str(
                row.get("entry_thesis", "")
                if current_weights.get(symbol, 0.0) > 0.0
                else row.get("cabinet_entry_thesis", "")
            )
            for symbol, row in rows.items()
        },
        max_names_per_thesis=thesis_hard_max,
        covariance_matrix=covariance,
        candidate_limit=optimizer_candidate_limit,
    )
    selected_types = [
        proposal.action_type
        for proposal in proposals
        if proposal.proposal_id in set(plan.selected_proposal_ids)
    ]
    selected_entry_symbols = {
        proposal.symbol
        for proposal in proposals
        if proposal.proposal_id in set(plan.selected_proposal_ids)
        and proposal.action_type == "new_entry"
    }
    (
        remaining_slots,
        released_slots,
        post_exit_available_slots,
    ) = _available_slots_after_exits(
        current_lots=current_lots,
        proposals=proposals,
        max_positions=int(context.top_n),
    )
    liveness_eligible = [
        proposal
        for proposal in proposals
        if proposal.action_type == "new_entry"
        and proposal.authority_tier in {"A", "B", "C"}
        and proposal.requested_lots == 1
        and proposal.robust_net_profit_amount > 0.0
        and not proposal.hard_veto_reasons
        and proposal.funding_cash_amount
        <= max(
            float(context.cash_amount) - float(context.cash_buffer_amount),
            0.0,
        )
        + 1e-8
        and current_exposure + proposal.exposure_delta
        <= strategic_budget + 1e-12
        and proposal.exposure_delta <= float(context.per_name_structural_cap) + 1e-12
        and proposal.downside_cvar_amount
        <= float(context.portfolio_stress_budget_amount) + 1e-12
    ]
    selected_buy_count = sum(
        action in {"new_entry", "winner_add", "loser_add", "replacement_buy"}
        for action in selected_types
    )
    liveness_preconditions = bool(
        str(context.safety.structural_regime_level).lower() in {"bull", "normal"}
        and len(current_lots) < int(context.soft_target_positions)
        and post_exit_available_slots > 0
        and not bool(context.safety.hard_freeze_active)
        and liveness_eligible
    )
    exact_buy_dominance = bool(
        plan.constraint_slacks.get("buy_plan_dominates_nonbuy", 0)
    )
    liveness_required = bool(liveness_preconditions and exact_buy_dominance)
    liveness_pass = bool(not liveness_required or selected_buy_count > 0)
    diagnostics = {
        "scap_v3_lean_version": LEAN_VERSION,
        "proposal_contract": LEAN_PROPOSAL_CONTRACT,
        "action_proposal_count": int(len(proposals)),
        "action_plan_count": 1,
        "optimizer_invocation_count": 1,
        "action_plan_id": plan.plan_id,
        "action_plan_selected_count": int(len(plan.selected_proposal_ids)),
        "action_plan_rejected_count": int(len(plan.rejected_proposals)),
        "selected_action_types": "|".join(selected_types),
        "lean_raw_entry_signal_count": len(raw_entry_signal_symbols),
        "lean_structural_feasible_entry_count": len(structural_entry_symbols),
        "lean_cash_feasible_entry_count": len(proposal_entry_symbols),
        "lean_slot_feasible_entry_count": (
            len(proposal_entry_symbols)
            if post_exit_available_slots > 0
            else 0
        ),
        "lean_released_position_slot_count": int(released_slots),
        "lean_post_exit_available_slot_count": int(
            post_exit_available_slots
        ),
        "lean_optimizer_selected_entry_count": len(selected_entry_symbols),
        "strategic_exposure_budget": strategic_budget,
        "desired_exposure_target": strategic_budget,
        "hard_exposure_ceiling": hard_exposure_ceiling,
        "confirmed_derisk_target": (
            confirmed_derisk_target
            if confirmed_derisk_target is not None
            else pd.NA
        ),
        "signal_supported_exposure": signal_supported,
        "integer_feasible_exposure": integer_feasible,
        "planned_exposure": float(plan.projected_exposure),
        "effective_deployment_target": float(
            authorization.effective_deployment_target
        ),
        "deployment_gap": float(plan.deployment_gap),
        "breadth_score": float(plan.breadth_score),
        "authority_penalty_amount": float(plan.authority_penalty_amount),
        "concentration_penalty_amount": float(
            plan.concentration_penalty_amount
        ),
        "risk_episode_id": str(authorization.risk_episode_id),
        "risk_reentry_blocked": bool(authorization.risk_reentry_blocked),
        "signal_cash_drag": max(strategic_budget - signal_supported, 0.0),
        "lot_cash_drag": max(signal_supported - integer_feasible, 0.0),
        "covariance_state": covariance_state,
        "authority_tier_a_count": int(
            data["scap_v31_authority_tier"].eq("A").sum()
        ),
        "authority_tier_b_count": int(
            data["scap_v31_authority_tier"].eq("B").sum()
        ),
        "authority_tier_c_count": int(
            data["scap_v31_authority_tier"].eq("C").sum()
        ),
        "authority_tier_d_count": int(
            data["scap_v31_authority_tier"].eq("D").sum()
        ),
        "scap_v31_liveness_required": liveness_required,
        "scap_v31_liveness_pass": liveness_pass,
        "scap_v31_liveness_eligible_count": len(liveness_eligible),
        "scap_v31_liveness_preconditions": liveness_preconditions,
        "scap_v31_exact_buy_plan_dominance": exact_buy_dominance,
        "scap_v31_best_buy_robust_objective": float(
            plan.constraint_slacks.get(
                "best_feasible_buy_robust_objective", 0.0
            )
        ),
        "scap_v31_best_nonbuy_robust_objective": float(
            plan.constraint_slacks.get(
                "best_feasible_nonbuy_robust_objective", 0.0
            )
        ),
        "legacy_allocation_authority": "shadow_only",
        "position_cap_mode": str(profile.get("position_cap_mode", "fixed")),
        "scaled_pool_count": pool_count,
        "scaled_optimizer_candidate_limit": optimizer_candidate_limit,
        "scaled_thesis_hard_max_names": thesis_hard_max,
        "action_plan_target_holding_count": int(
            sum(
                int(lots) > 0
                for lots in plan.target_lots_by_symbol.values()
            )
        ),
        "unresolved_safety_exposure": max(
            current_exposure
            - planned_safety_sell_weight
            - (
                confirmed_derisk_target
                if confirmed_derisk_target is not None
                else hard_exposure_ceiling
            ),
            0.0,
        ),
        "planned_safety_sell_weight": planned_safety_sell_weight,
        "constraint_cash_reserve": float(authorization.cash_buffer_amount),
        "scap_v32_pool_count": int(
            data.get("scap_v32_pool_id", pd.Series(dtype=object)).nunique()
        ),
        "scap_v32_deduplicated_symbol_count": int(len(rows)),
        "scap_v32_pool_contract": "scap_v32_thesis_pool_preserving_v1",
    }
    if diagnostics["optimizer_invocation_count"] != 1:
        raise RuntimeError("SCAP-V3 Lean optimizer invocation invariant failed")
    if not liveness_pass:
        raise RuntimeError(
            "SCAP-V3.2 liveness failed: positive A/B/C one-lot proposal had all "
            "factual hard-constraint slack but the ActionPlan selected no buy"
        )
    return LeanDecision(
        proposals=tuple(proposals),
        plan=plan,
        authorization=authorization,
        proposal_rows=proposal_rows,
        diagnostics=diagnostics,
    )


def _append_exposure_cap_safety_exits(
    proposals,
    proposal_rows,
    *,
    context,
    rows,
    current_weights,
    current_lots,
    current_exposure,
    strategic_budget,
    derisk_confirmed: bool = False,
) -> float:
    """Create factual full-position exits until the next-session cap is reachable."""
    required_reduction = max(float(current_exposure) - float(strategic_budget), 0.0)
    if required_reduction <= 1e-12:
        return 0.0
    profile = dict(context.execution_cost_profile or {})
    no_trade_band = max(
        float(profile.get("scap_safety_no_trade_band", 0.0) or 0.0),
        0.0,
    )
    risk_level = str(context.safety.risk_level).strip().lower()
    confirmation_days = max(
        int(profile.get("scap_safety_confirmation_days", 1) or 1),
        1,
    )
    confirmed = bool(
        derisk_confirmed
        or risk_level == "high"
        or bool(context.safety.hard_freeze_active)
        or int(context.safety.trigger_streak_days) >= confirmation_days
    )
    if not confirmed:
        return 0.0
    if risk_level != "high" and required_reduction <= no_trade_band + 1e-12:
        return 0.0
    already_forced = {
        proposal.symbol
        for proposal in proposals
        if proposal.action_type in {"hard_exit", "safety_exit"}
    }
    planned_weight = sum(
        float(current_weights.get(symbol, 0.0))
        for symbol in already_forced
    )
    held_rows = [
        (symbol, rows.get(symbol))
        for symbol in current_weights
        if float(current_weights.get(symbol, 0.0)) > 0.0
        and symbol not in already_forced
        and rows.get(symbol) is not None
    ]
    held_rows.sort(
        key=lambda item: (
            _number(item[1].get("comparable_expected_alpha")),
            -float(current_weights.get(item[0], 0.0)),
            item[0],
        )
    )
    for symbol, row in held_rows:
        if planned_weight + 1e-12 >= required_reduction:
            break
        old_weight = float(current_weights.get(symbol, 0.0))
        proposal = _proposal(
            context,
            symbol=symbol,
            action_type="safety_exit",
            lots=max(int(current_lots.get(symbol, 1)), 1),
            expected=0.0,
            robust=0.0,
            downside=0.0,
            cost=_number(row.get("scap_estimated_total_cost_amount")),
            funding=0.0,
            suffix="exposure_cap_safety_exit",
            source="exposure_authorization",
        )
        proposals.append(proposal)
        proposal_rows[proposal.proposal_id] = row
        planned_weight += old_weight
    return min(planned_weight, float(current_exposure))


def _append_held_proposals(
    proposals,
    proposal_rows,
    *,
    context,
    symbol,
    row,
    old_weight,
    lot_cash,
    lot_weight,
) -> None:
    exit_reason = str(row.get("position_exit_reason", "") or "")
    exit_state = bool(row.get("exit_state", False))
    if exit_state:
        # `exit_state` is emitted only after lifecycle confirmation. Once it
        # is active it is a mandatory position-state transition, not an alpha
        # buy competing for positive profit.
        hard = True
        expected_hold = _number(row.get("comparable_expected_alpha"))
        position_amount = float(context.nav_amount) * old_weight
        robust = 0.0 if hard else max(-expected_hold * position_amount, 0.0)
        action_type = "hard_exit"
        proposal = _proposal(
            context,
            symbol=symbol,
            action_type=action_type,
            lots=max(int(round(old_weight / max(lot_weight, 1e-12))), 1),
            expected=robust,
            robust=robust,
            downside=0.0,
            cost=_number(row.get("scap_estimated_total_cost_amount")),
            funding=0.0,
            suffix=action_type,
            source="position_lifecycle_evidence",
        )
        proposals.append(proposal)
        proposal_rows[proposal.proposal_id] = row
        return
    if lot_cash <= 0.0 or lot_weight <= 0.0:
        return
    unrealized = float("nan")
    for field in (
        "net_unrealized_return",
        "position_unrealized_return",
        "unrealized_return",
    ):
        candidate_unrealized = _number(row.get(field), default=float("nan"))
        if math.isfinite(candidate_unrealized):
            unrealized = candidate_unrealized
            break
    if not math.isfinite(unrealized):
        unrealized = 0.0
    # Lifecycle `add_layer` is the *next buy count*: an initial one-lot
    # holding therefore exposes add_layer=2 for its first possible add.
    # Convert it to completed add count for the profile-owned layer limit.
    layer = max(int(_number(row.get("add_layer"))) - 2, 0)
    base_utility = _number(row.get("add_expected_net_profit_lcb"))
    add_review_passed = bool(row.get("winner_add_review_passed", False))
    entry_authority_tier = str(row.get("entry_authority_tier", "D") or "D")
    current_authority_tier = str(
        row.get(
            "scap_v32_current_authority_tier",
            row.get("scap_v31_authority_tier", "D"),
        )
        or "D"
    )
    lifecycle_winner_allowed = bool(row.get("add_allowed", False)) and str(
        row.get("add_decision_type", "")
    ) == "winner_pyramiding"
    # The lifecycle arbiter is the sole source of add permission: it already
    # checks the realised gain trigger, hold-support quantile, positive
    # incremental utility, cooldown, profit protection and name cap.  A C
    # starter that passes all of those factual checks earns one B-sized add;
    # this is a realised-evidence promotion, not a fabricated forecast tier.
    if current_authority_tier == "C" and lifecycle_winner_allowed:
        current_authority_tier = "B"
    if base_utility <= 0.0 and current_authority_tier in {"A", "B"}:
        current_return = _number(
            row.get(
                "scap_v31_decision_expected_return",
                row.get("comparable_alpha_lcb", 0.0),
            )
        )
        base_utility = (
            lot_cash * current_return
            - _number(row.get("scap_estimated_total_cost_amount"))
        )
    max_winner_add_layers = max(
        int(
            (context.execution_cost_profile or {}).get(
                "scap_max_winner_add_layers",
                0,
            )
            or 0
        ),
        0,
    )
    authority_snapshot_id = str(
        row.get("scap_authority_snapshot_id", "") or ""
    )
    if (
        context.winner_add_enabled
        and lifecycle_winner_allowed
        and layer < max_winner_add_layers
        and add_review_passed
        and current_authority_tier in {"A", "B"}
        and bool(authority_snapshot_id)
    ):
        # Lifecycle owns the trigger schedule. Its positive robust incremental
        # utility is the optimizer input; do not apply a second hard-coded
        # trigger or a second confidence transform here.
        remaining_name_weight = max(
            float(getattr(context, "per_name_structural_cap", 1.0))
            - float(old_weight),
            0.0,
        )
        max_by_name = (
            int(math.floor(remaining_name_weight / lot_weight))
            if lot_weight > 0.0
            else 0
        )
        spendable_cash = max(
            float(getattr(context, "cash_amount", lot_cash))
            - float(getattr(context, "cash_buffer_amount", 0.0)),
            0.0,
        )
        max_by_cash = (
            int(math.floor(spendable_cash / lot_cash))
            if lot_cash > 0.0
            else 0
        )
        authority_lots = max(
            int(_number(row.get("scap_v31_max_lots"), default=1.0)),
            0,
        )
        add_lots = min(max_by_name, max_by_cash, authority_lots)
        if add_lots <= 0:
            return
        decision_date = getattr(
            context, "decision_date", pd.Timestamp("2000-01-01")
        )
        rule = trading_rule_for(symbol, trade_date=decision_date)
        lot_shares = max(float(rule.minimum_buy_quantity), 1.0)
        inferred_price = lot_cash / lot_shares
        exact_total_cost = round_trip_cost_amount(
            symbol=symbol,
            price=inferred_price,
            shares=lot_shares * add_lots,
            trade_date=decision_date,
        )
        one_lot_cost = max(
            _number(row.get("scap_estimated_total_cost_amount")),
            0.0,
        )
        gross_robust_profit = (
            max(base_utility, 0.0) + one_lot_cost
        ) * add_lots
        scaled_base_utility = gross_robust_profit - exact_total_cost
        if scaled_base_utility <= 0.0:
            return
        scaled_robust = scaled_base_utility
        proposal = _proposal(
            context,
            symbol=symbol,
            action_type="winner_add",
            lots=add_lots,
            expected=scaled_base_utility,
            robust=scaled_robust,
            downside=lot_cash * 0.15 * add_lots,
            cost=exact_total_cost,
            funding=lot_cash * add_lots,
            suffix=f"winner_add_{layer + 1}",
            source="position_lifecycle_evidence",
            authority_tier=current_authority_tier,
            authority_snapshot_id=authority_snapshot_id,
            thesis=str(row.get("entry_thesis", "") or ""),
        )
        proposals.append(proposal)
        proposal_rows[proposal.proposal_id] = row
    if context.loser_add_enabled and -0.10 <= unrealized <= -0.04 and layer < 1:
        proposal = _proposal(
            context,
            symbol=symbol,
            action_type="loser_add",
            lots=1,
            expected=max(base_utility, 0.0),
            robust=base_utility,
            downside=lot_cash * 0.20,
            cost=_number(row.get("scap_estimated_total_cost_amount")),
            funding=lot_cash,
            suffix="loser_add_1",
            source="position_lifecycle_evidence",
        )
        proposals.append(proposal)
        proposal_rows[proposal.proposal_id] = row


def _proposal(
    context,
    *,
    symbol,
    action_type,
    lots,
    expected,
    robust,
    downside,
    cost,
    funding,
    suffix,
    source,
    authority_tier="A",
    thesis="",
    pool_id="",
    pool_memberships=(),
    primary_score=0.0,
    primary_rank=0.0,
    unit_capital_robust_return=0.0,
    authority_penalty_amount=0.0,
    execution_class=None,
    must_execute=None,
    authority_snapshot_id=None,
) -> ActionProposal:
    return ActionProposal(
        proposal_id=f"{context.decision_id}|{symbol}|{suffix}",
        decision_id=str(context.decision_id),
        symbol=str(symbol),
        action_type=str(action_type),
        source_module=str(source),
        requested_lots=max(int(lots), 1),
        baseline_action="hold_cash" if action_type == "new_entry" else "hold_position",
        horizon_sessions=max(int(context.forecast_horizon_sessions), 1),
        expected_net_profit_amount=float(expected),
        robust_net_profit_amount=float(robust),
        downside_cvar_amount=max(float(downside), 0.0),
        exact_cost_amount=max(float(cost), 0.0),
        funding_cash_amount=max(float(funding), 0.0),
        cash_release_amount=(
            max(
                float(context.current_weights.get(symbol, 0.0))
                * float(context.nav_amount)
                - max(float(cost), 0.0),
                0.0,
            )
            if action_type
            in {"exit", "hard_exit", "safety_exit", "replacement_sell"}
            else 0.0
        ),
        exposure_delta=(
            -float(context.current_weights.get(symbol, 0.0))
            if action_type in {"exit", "hard_exit", "safety_exit", "replacement_sell"}
            else float(funding) / max(float(context.nav_amount), 1e-12)
        ),
        authority_tier=str(authority_tier),
        thesis=str(thesis),
        pool_id=str(pool_id),
        pool_memberships=tuple(str(value) for value in pool_memberships),
        primary_score=float(primary_score),
        primary_rank=float(primary_rank),
        unit_capital_robust_return=float(unit_capital_robust_return),
        authority_penalty_amount=max(float(authority_penalty_amount), 0.0),
        execution_class=str(
            execution_class
            or (
                "mandatory_exit"
                if action_type in {"hard_exit", "safety_exit"}
                else "alpha"
            )
        ),
        must_execute=bool(
            action_type in {"hard_exit", "safety_exit"}
            if must_execute is None
            else must_execute
        ),
        authority_snapshot_id=str(
            authority_snapshot_id or f"{context.decision_id}|authority"
        ),
    )


def _attach_pool_contract(data: pd.DataFrame) -> pd.DataFrame:
    """Attach a PIT-safe pool identity without changing the cabinet score."""
    out = data.copy()
    thesis = out.get(
        "cabinet_entry_thesis",
        pd.Series("unclassified", index=out.index),
    ).fillna("unclassified").astype(str).str.strip()
    thesis = thesis.mask(thesis.eq(""), "unclassified")
    out["scap_v32_pool_id"] = thesis
    primary = pd.to_numeric(
        out.get(
            "primary_score",
            out.get(
                "cabinet_native_final_score",
                pd.Series(0.0, index=out.index),
            ),
        ),
        errors="coerce",
    ).fillna(0.0)
    out["scap_v32_primary_score"] = primary
    out["scap_v32_pool_rank"] = (
        out.groupby("scap_v32_pool_id", sort=False)[
            "scap_v32_primary_score"
        ]
        .rank(method="first", ascending=False)
        .astype(float)
    )
    return out


def _deduplicate_pool_rows(data: pd.DataFrame) -> dict[str, pd.Series]:
    """Return one proposal row per symbol while preserving all pool labels."""
    rows: dict[str, pd.Series] = {}
    ordered = data.sort_values(
        ["symbol", "scap_v32_primary_score", "scap_v32_pool_id"],
        ascending=[True, False, True],
        kind="mergesort",
    )
    for symbol, group in ordered.groupby("symbol", sort=True):
        row = group.iloc[0].copy()
        memberships = sorted(
            {
                str(value)
                for value in group["scap_v32_pool_id"].dropna()
                if str(value)
            }
        )
        row["scap_v32_pool_memberships"] = "|".join(memberships)
        rows[str(symbol)] = row
    return rows


def _entry_hard_vetoes(
    row,
    lot_cash: float,
    lot_weight: float,
    *,
    structural_cap: float = 0.40,
) -> tuple[str, ...]:
    reasons = []
    if lot_cash <= 0.0 or lot_weight <= 0.0:
        reasons.append("invalid_or_missing_lot_price")
    if lot_weight > max(float(structural_cap), 0.0) + 1e-12:
        reasons.append("one_lot_exceeds_structural_cap")
    if "mainline_v3_lot_feasible" in row.index and not bool(
        row.get("mainline_v3_lot_feasible", False)
    ):
        reasons.append("factual_lot_infeasible")
    state = str(row.get("position_state", "") or "").strip().lower()
    if state in {"cooldown", "exiting", "protecting_profit"}:
        reasons.append(f"factual_position_state_{state}")
    if bool(row.get("exit_state", False)):
        reasons.append("factual_exit_state")
    return tuple(reasons)


def _available_slots_after_exits(
    *,
    current_lots,
    proposals,
    max_positions: int,
) -> tuple[int, int, int]:
    """Count slots after factual full exits, not only before the ActionPlan."""
    remaining = max(int(max_positions) - len(current_lots), 0)
    released = len(
        {
            proposal.symbol
            for proposal in proposals
            if proposal.action_type in {
                "exit",
                "hard_exit",
                "safety_exit",
                "replacement_sell",
            }
            and proposal.symbol in current_lots
        }
    )
    return remaining, released, remaining + released


def _shrink_covariance(matrix: pd.DataFrame | None) -> tuple[pd.DataFrame | None, str]:
    if matrix is None or matrix.empty:
        return None, "fallback_thesis_caps"
    numeric = matrix.apply(pd.to_numeric, errors="coerce").fillna(0.0)
    if numeric.shape[0] != numeric.shape[1]:
        return None, "fallback_thesis_caps"
    diagonal = pd.DataFrame(0.0, index=numeric.index, columns=numeric.columns)
    for symbol in numeric.index.intersection(numeric.columns):
        diagonal.at[symbol, symbol] = max(float(numeric.at[symbol, symbol]), 0.0)
    return 0.70 * numeric + 0.30 * diagonal, "shrunk_covariance_70_30"


def _number(value, default: float = 0.0) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(numeric) if pd.notna(numeric) and math.isfinite(float(numeric)) else float(default)
