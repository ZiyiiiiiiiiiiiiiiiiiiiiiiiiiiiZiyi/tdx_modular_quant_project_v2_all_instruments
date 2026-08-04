"""SCAP-V3 Lean proposal factory and single-plan orchestration.

This module owns no execution or accounting state.  It converts factual
candidate/position snapshots into comparable integer-lot proposals and calls
the sole optimizer exactly once.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import time

import pandas as pd

from functions.decision_council.action_utility import (
    assess_economic_order,
    buy_cash_required_amount,
    estimate_lifecycle_cost,
    round_trip_cost_amount,
    sell_cash_released_amount,
    single_side_cost_amount,
)
from functions.decision_council.capital_scaling import (
    resolve_optimizer_search_budget,
    scaled_candidate_budgets,
)
from functions.decision_council.candidate_pool_contract import (
    CANDIDATE_POOL_CONTRACT_VERSION,
    select_feasible_candidate_pool,
)
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
from functions.decision_council.portfolio_constraint_contract import (
    PolicyBand,
    authorize_recovery,
    project_mandatory_actions,
    resolve_conditional_deployment_bounds,
)


LEAN_VERSION = "small_capital_aggressive_profit_v3_3"
LEAN_PROPOSAL_CONTRACT = "scap_v33_economic_portfolio_proposal_factory_v1"


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
            allow_synthetic_compatibility=bool(
                (context.execution_cost_profile or {}).get(
                    "scap_allow_synthetic_authority",
                    False,
                )
            ),
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
    current_lots: dict[str, int] = {
        str(symbol): max(int(lots), 1)
        for symbol, lots in dict(
            getattr(context, "current_lots_by_symbol", None) or {}
        ).items()
        if int(lots) > 0
    }
    raw_entry_signal_symbols: set[str] = {
        symbol
        for symbol, row in rows.items()
        if float(context.current_weights.get(symbol, 0.0)) <= 0.0
        and (
            _number(row.get("scap_v31_decision_expected_return")) > 0.0
            or _number(row.get("scap_candidate_utility")) > 0.0
        )
    }
    structural_entry_symbols: set[str] = set()
    proposal_entry_symbols: set[str] = set()
    if "scap_action_candidate" in data.columns:
        entry_shortlist = frozenset(
            data.loc[
                data["scap_action_candidate"].fillna(False).astype(bool),
                "symbol",
            ].astype(str)
        )
        candidate_pool_runtime_state = "upstream_authoritative_pool"
    else:
        # Explicit compatibility for direct contract tests.  It calls the same
        # shared pool contract; there is no second Lean ranking formula.
        selected_index, _, _ = select_feasible_candidate_pool(
            data,
            limit=max(int(profile.get("scap_candidate_pool_limit", 32) or 32), 1),
            per_pool_reserve=max(
                int(profile.get("scap_candidate_pool_per_thesis", 2) or 2), 1
            ),
        )
        entry_shortlist = frozenset(data.loc[selected_index, "symbol"].astype(str))
        candidate_pool_runtime_state = "shared_contract_compatibility_fallback"
    proposal_source_rows = {
        symbol: row
        for symbol, row in rows.items()
        if float(context.current_weights.get(symbol, 0.0)) > 0.0
        or symbol in entry_shortlist
    }

    for symbol, row in proposal_source_rows.items():
        old_weight = current_weights.get(symbol, 0.0)
        minimum_quantity = max(
            int(_number(row.get("mainline_v3_minimum_buy_quantity"), 100.0)),
            1,
        )
        price = _number(row.get("close_nominal", row.get("close")))
        legacy_lot_cash = _number(
            row.get("mainline_v3_one_lot_cash_required")
        )
        lot_market_notional = _number(
            row.get("mainline_v3_one_lot_market_notional")
        )
        if lot_market_notional <= 0.0 and price > 0.0:
            lot_market_notional = price * minimum_quantity
        if lot_market_notional <= 0.0 and legacy_lot_cash > 0.0:
            # Compatibility-only synthetic fixtures may lack a market price.
            # Keep the fallback explicit; production rows carry close_nominal.
            lot_market_notional = legacy_lot_cash
        if price <= 0.0 and lot_market_notional > 0.0:
            price = lot_market_notional / minimum_quantity
        lot_cash = (
            buy_cash_required_amount(
                symbol=symbol,
                price=price,
                shares=float(minimum_quantity),
                trade_date=context.decision_date,
                cost_profile=context.execution_cost_profile,
            )
            if price > 0.0
            else legacy_lot_cash
        )
        lot_weight = (
            lot_market_notional / max(float(context.nav_amount), 1e-12)
            if lot_market_notional > 0.0
            else 0.0
        )
        exact_current_lots = dict(getattr(context, "current_lots_by_symbol", None) or {})
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
                lot_market_notional=lot_market_notional,
                lot_weight=lot_weight,
            )
            continue

        utility = _number(row.get("scap_candidate_utility"))
        authority_tier = str(row.get("scap_v31_authority_tier", "D") or "D")
        decision_return = _number(row.get("scap_v31_decision_expected_return"))
        decision_return_basis = str(
            row.get(
                "scap_decision_return_basis",
                profile.get("scap_candidate_reward_basis", "lcb"),
            )
            or "lcb"
        ).strip().lower()
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
        # Build economically comparable proposals before final authorization.
        # A mandatory exit can create a same-plan recovery requirement, which
        # is unknowable from the pre-trade catch-up flag.
        max_by_name = int(
            math.floor(max(float(context.per_name_structural_cap), 0.0) / lot_weight)
        ) if lot_weight > 0.0 else 0
        max_lots = min(
            max(max_by_name, 0),
            int(_number(row.get("scap_v31_max_lots"), 0.0)),
        )
        if max_lots > 0:
            proposal_entry_symbols.add(symbol)
        for lots in range(1, max_lots + 1):
            market_notional = lot_market_notional * lots
            buy_cash = buy_cash_required_amount(
                symbol=symbol,
                price=price,
                shares=float(minimum_quantity * lots),
                trade_date=context.decision_date,
                cost_profile=context.execution_cost_profile,
            )
            if buy_cash > max(
                float(context.cash_amount) - float(context.cash_buffer_amount),
                0.0,
            ) + 1e-8:
                break
            exact_cost = round_trip_cost_amount(
                symbol=symbol,
                price=price,
                shares=float(minimum_quantity * lots),
                trade_date=context.decision_date,
                cost_profile=context.execution_cost_profile,
            )
            # Candidate value contains conservative return and full lifecycle
            # cost only. Tail and concentration risk are charged once by the
            # portfolio objective.
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
            authority_penalty = market_notional * authority_penalty_rate
            horizon = max(int(context.forecast_horizon_sessions), 1)
            p_win_lower = min(
                max(_number(row.get(f"p_win_{horizon}d_wilson_lower")), 0.0),
                1.0,
            )
            avg_win_return = max(
                _number(row.get(f"avg_win_{horizon}d_by_bucket")), 0.0
            )
            avg_loss_return = max(
                _number(row.get(f"avg_loss_{horizon}d_by_bucket")), 0.0
            )
            calibration_state = str(
                row.get(f"entry_calibration_state_{horizon}d", "prior_only")
                or "prior_only"
            ).lower()
            calibration_effective_samples = max(
                _number(
                    row.get(
                        f"entry_calibration_effective_sample_size_{horizon}d"
                    )
                ),
                0.0,
            )
            warming_effective_samples = max(
                int(profile.get("scap_calibration_warming_effective_samples", 30)),
                1,
            )
            coverage_authorized = bool(
                calibration_state in {"calibrated", "recovering"}
                and calibration_effective_samples >= warming_effective_samples
                and p_win_lower > 0.0
                and avg_win_return > 0.0
                and avg_loss_return > 0.0
            )
            expected_positive_pnl = (
                p_win_lower * avg_win_return * market_notional
                if coverage_authorized
                else 0.0
            )
            expected_loss_pnl = (
                (1.0 - p_win_lower) * avg_loss_return * market_notional
                if coverage_authorized
                else 0.0
            )
            tail_loss_rate = max(
                _number(row.get(f"downside_cvar_{horizon}d_by_bucket"), 0.15),
                0.002,
            )
            lifecycle_cost = estimate_lifecycle_cost(
                symbol=symbol,
                price=price,
                shares=float(minimum_quantity * lots),
                trade_date=context.decision_date,
                cost_profile=context.execution_cost_profile,
            )
            if decision_return > 0.0:
                expected_profit = (
                    point_return * market_notional - exact_cost
                )
                robust_profit = (
                    decision_return * market_notional
                    - exact_cost
                )
            else:
                # Compatibility for already-net synthetic/legacy proposals.
                expected_profit = utility * lots
                robust_profit = utility * lots
            robust_profit -= max(
                lifecycle_cost.total_lifecycle_cost_amount - exact_cost,
                0.0,
            )
            economic_assessment = (
                assess_economic_order(
                    market_notional_amount=market_notional,
                    lifecycle_cost=lifecycle_cost,
                    conservative_gross_profit_amount=(
                        expected_positive_pnl
                        if coverage_authorized
                        else max(decision_return, 0.0) * market_notional
                    ),
                    robust_net_profit_amount=robust_profit - authority_penalty,
                    cost_profile=context.execution_cost_profile,
                    high_confidence_exception=bool(
                        authority_tier == "A" and coverage_authorized
                    ),
                )
                if bool(profile.get("scap_economic_order_contract_enabled", False))
                else None
            )
            economic_vetoes = (
                ("economic_order:" + economic_assessment.reason,)
                if economic_assessment is not None and not economic_assessment.passed
                else ()
            )
            calendar_vetoes = ()
            proposal = _proposal(
                context,
                symbol=symbol,
                action_type="new_entry",
                lots=lots,
                expected=expected_profit,
                robust=robust_profit,
                downside=market_notional * tail_loss_rate,
                cost=exact_cost,
                funding=buy_cash,
                market_notional=market_notional,
                buy_cash_required=buy_cash,
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
                    / max(market_notional, 1.0)
                ),
                authority_penalty_amount=authority_penalty,
                hard_veto_reasons=economic_vetoes + calendar_vetoes,
                lifecycle_cost_amount=lifecycle_cost.total_lifecycle_cost_amount,
                round_trip_cost_ratio=lifecycle_cost.round_trip_cost_ratio,
                lifecycle_cost_to_gross_profit_ratio=(
                    economic_assessment.lifecycle_cost_to_gross_profit_ratio
                    if economic_assessment is not None
                    else 0.0
                ),
                minimum_economic_order_amount=(
                    economic_assessment.minimum_economic_order_amount
                    if economic_assessment is not None
                    else 0.0
                ),
                economic_order_pass=(
                    economic_assessment.passed
                    if economic_assessment is not None
                    else True
                ),
                economic_order_reason=(
                    economic_assessment.reason
                    if economic_assessment is not None
                    else "contract_disabled"
                ),
                economic_order_warnings=(
                    economic_assessment.warnings
                    if economic_assessment is not None
                    else ()
                ),
                p_win_lower=p_win_lower if coverage_authorized else 0.0,
                avg_win_return=avg_win_return if coverage_authorized else 0.0,
                avg_loss_return=avg_loss_return if coverage_authorized else 0.0,
                expected_positive_pnl_amount=expected_positive_pnl,
                expected_loss_pnl_amount=expected_loss_pnl,
                coverage_evidence_authorized=coverage_authorized,
                allocation_sleeve="exploration",
                calibration_evidence_state=calibration_state,
                calibration_effective_sample_size=calibration_effective_samples,
                scenario_contract_id=str(
                    profile.get(
                        "scap_incremental_scenario_contract_version",
                        "scap_incremental_scenario_cvar_v1",
                    )
                ),
                decision_return_basis=str(decision_return_basis),
            )
            proposals.append(proposal)
            proposal_rows[proposal.proposal_id] = row

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
    policy_band = getattr(context, "policy_band", None)
    if policy_band is None:
        policy_band = PolicyBand(
            state="compatibility",
            holding_floor=0,
            holding_target=max(int(context.soft_target_positions), 0),
            exposure_lower=0.0,
            exposure_target=strategic_budget,
            exposure_upper=max(strategic_budget, hard_exposure_ceiling),
            disaster_ceiling=max(strategic_budget, hard_exposure_ceiling),
            policy_version="compatibility_context_v1",
        )
    mandatory_projection = project_mandatory_actions(
        current_lots=current_lots,
        current_weights=current_weights,
        current_cash=float(context.cash_amount),
        proposals=proposals,
    )
    wealth_epsilon_amount = max(
        float(profile.get("scap_wealth_materiality_epsilon_amount", 1.0)),
        0.0,
    )
    # Product policy owns the position ceiling.  Runtime capacity may make the
    # policy infeasible, but it must never silently broaden it.  Existing
    # holdings are grandfathered long enough for explicit exit proposals.
    effective_holding_ceiling = max(
        min(
            max(int(context.top_n), 0),
            max(int(policy_band.holding_ceiling), 0),
        ),
        int(mandatory_projection.post_mandatory_holding_count),
        1,
    )
    deployment_bounds = resolve_conditional_deployment_bounds(
        policy_band=policy_band,
        mandatory_projection=mandatory_projection,
        hard_holding_ceiling=effective_holding_ceiling,
        hard_exposure_ceiling=hard_exposure_ceiling,
        positive_feasible_proposals=proposals,
        wealth_epsilon_amount=wealth_epsilon_amount,
    )
    post_mandatory_recovery = authorize_recovery(
        decision_id=str(context.decision_id),
        mandatory_projection=mandatory_projection,
        bounds=deployment_bounds,
        configured_max_new_names=int(
            profile.get("scap_recovery_max_new_names_per_day", 1)
        ),
        configured_daily_exposure_cap=float(
            profile.get("scap_recovery_daily_exposure_cap", 0.15)
        ),
        deadline_sessions=int(profile.get("scap_recovery_window_sessions", 5)),
        safety_blocked=bool(
            context.safety.hard_freeze_active
            or str(context.safety.risk_level).strip().lower() in {"critical"}
            or str(context.safety.structural_regime_level).strip().lower()
            in {"crisis"}
        ),
        prior_episode_id=str(getattr(context, "recovery_episode_id", "") or ""),
        prior_episode_day=max(
            int(getattr(context, "recovery_episode_day", 0) or 0),
            0,
        ),
    )
    signal_supported, integer_feasible = _constructive_entry_exposure_bounds(
        proposals=proposals,
        current_lots=current_lots,
        current_exposure=current_exposure,
        max_positions=effective_holding_ceiling,
        available_cash=max(float(context.cash_amount), 0.0),
        cash_buffer=max(float(context.cash_buffer_amount), 0.0),
        strategic_budget=strategic_budget,
    )
    covariance = context.covariance_matrix
    covariance_state = (
        str(
            getattr(covariance, "attrs", {}).get(
                "estimator",
                "covariance_complete_coverage",
            )
        )
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
        per_name_stress_budget_amount=min(
            float(context.nav_amount)
            * float(context.per_name_structural_cap)
            * 0.40,
            float(context.nav_amount)
            * float(profile.get("scap_per_name_stress_budget_ratio", 0.03) or 0.03),
        ),
        portfolio_stress_budget_amount=max(
            float(context.portfolio_stress_budget_amount), 0.0
        ),
        new_entry_allowed=(
            not bool(context.safety.hard_freeze_active)
            and bool(
                context.allow_normal_rebalance
                or context.catchup_allowed
                or post_mandatory_recovery.authorized
            )
            and (
                not risk_episode_active
                or bool(context.catchup_allowed)
                or post_mandatory_recovery.authorized
            )
            and mandatory_projection.post_mandatory_exposure
            < strategic_budget - 1e-12
            and not (
                bool(profile.get("scap_block_new_entry_during_high_risk", True))
                and risk_level == "high"
            )
        ),
        add_allowed=(
            not bool(context.safety.hard_freeze_active)
            and current_exposure < strategic_budget - 1e-12
        ),
        # Lean has no atomic paired replacement proposal factory yet.  Fail
        # closed instead of advertising an unreachable permission.
        replacement_allowed=False,
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
        effective_position_cap=effective_holding_ceiling,
        pool_count=pool_count,
        optimizer_multiple=float(
            profile.get("scap_optimizer_candidate_multiple", 4.0) or 4.0
        ),
        search_cap=int(
            profile.get("scap_optimizer_candidate_search_cap", 96) or 96
        ),
    )
    search_budget = resolve_optimizer_search_budget(profile)
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
    optimizer_candidate_limit = min(
        int(optimizer_candidate_limit),
        int(search_budget.prefilter_symbol_limit),
    )
    optimizer_started = time.perf_counter()
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
        max_names_per_thesis=min(
            int(thesis_hard_max),
            int(policy_band.maximum_names_per_pool),
        ),
        covariance_matrix=covariance,
        scenario_return_matrix=context.scenario_return_matrix,
        candidate_limit=optimizer_candidate_limit,
        minimum_profit_coverage_ratio=float(
            profile.get("scap_minimum_profit_coverage_ratio", 1.25) or 1.25
        ),
        minimum_profit_coverage_probability=float(
            profile.get("scap_minimum_profit_coverage_probability", 0.55)
            or 0.55
        ),
        coverage_correlation_floor=float(
            profile.get("scap_coverage_correlation_floor", 0.35)
        ),
        minimum_coverage_evidence_names=int(
            max(
                int(profile.get("scap_minimum_coverage_evidence_names", 1) or 1),
                int(policy_band.holding_target),
            )
        ),
        coverage_mode=str(
            profile.get("scap_profit_coverage_mode", "diagnostic_shadow")
            or "diagnostic_shadow"
        ),
        incremental_cvar_confidence=float(
            profile.get("scap_incremental_cvar_confidence", 0.95)
        ),
        incremental_cvar_risk_aversion=float(
            profile.get("scap_incremental_cvar_risk_aversion", 0.05)
        ),
        model_uncertainty_risk_aversion=float(
            profile.get("scap_model_uncertainty_risk_aversion", 0.10)
        ),
        calibration_warming_effective_samples=int(
            profile.get("scap_calibration_warming_effective_samples", 30)
        ),
        calibration_mature_effective_samples=int(
            profile.get("scap_calibration_mature_effective_samples", 100)
        ),
        max_new_buy_names=(
            int(post_mandatory_recovery.max_new_names_today)
            if bool(
                post_mandatory_recovery.authorized
                and not context.allow_normal_rebalance
            )
            else None
        ),
        max_incremental_buy_exposure=(
            float(post_mandatory_recovery.max_buy_exposure_today)
            if bool(
                post_mandatory_recovery.authorized
                and not context.allow_normal_rebalance
            )
            else None
        ),
        minimum_positions=int(deployment_bounds.conditional_holding_floor),
        minimum_exposure=float(deployment_bounds.conditional_exposure_floor),
        target_positions=min(
            int(policy_band.holding_target),
            int(deployment_bounds.hard_holding_ceiling),
        ),
        target_exposure=min(
            float(policy_band.exposure_target),
            float(deployment_bounds.hard_exposure_ceiling),
        ),
        wealth_materiality_epsilon_amount=float(wealth_epsilon_amount),
        minimum_active_pool_size=int(policy_band.minimum_active_pool_size),
        minimum_effective_n_ratio=float(policy_band.minimum_effective_n_ratio),
        minimum_pool_count=int(policy_band.minimum_pool_count),
        exhaustive_max_positions=int(search_budget.exact_max_positions),
        beam_width=int(search_budget.beam_width),
    )
    optimizer_elapsed_seconds = time.perf_counter() - optimizer_started
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
        "policy_band_state": str(policy_band.state),
        "policy_holding_floor": int(policy_band.holding_floor),
        "policy_holding_target": int(policy_band.holding_target),
        "policy_holding_ceiling": int(policy_band.holding_ceiling),
        "policy_minimum_active_pool_size": int(
            policy_band.minimum_active_pool_size
        ),
        "policy_minimum_effective_n_ratio": float(
            policy_band.minimum_effective_n_ratio
        ),
        "policy_minimum_pool_count": int(policy_band.minimum_pool_count),
        "policy_maximum_names_per_pool": int(
            policy_band.maximum_names_per_pool
        ),
        "policy_exposure_lower": float(policy_band.exposure_lower),
        "policy_exposure_target": float(policy_band.exposure_target),
        "policy_exposure_upper": float(policy_band.exposure_upper),
        "policy_disaster_exposure_ceiling": float(
            policy_band.disaster_ceiling
        ),
        "post_mandatory_holding_count": int(
            mandatory_projection.post_mandatory_holding_count
        ),
        "post_mandatory_exposure": float(
            mandatory_projection.post_mandatory_exposure
        ),
        "post_mandatory_cash": float(
            mandatory_projection.post_mandatory_cash
        ),
        "conditional_holding_floor": int(
            deployment_bounds.conditional_holding_floor
        ),
        "conditional_exposure_floor": float(
            deployment_bounds.conditional_exposure_floor
        ),
        "daily_effective_holding_ceiling": int(
            deployment_bounds.hard_holding_ceiling
        ),
        "daily_effective_exposure_ceiling": float(
            deployment_bounds.hard_exposure_ceiling
        ),
        "positive_feasible_new_name_count": int(
            deployment_bounds.positive_feasible_new_name_count
        ),
        "post_mandatory_recovery_authorized": bool(
            post_mandatory_recovery.authorized
        ),
        "post_mandatory_recovery_reason": str(
            post_mandatory_recovery.block_reason
        ),
        "post_mandatory_recovery_episode_id": str(
            post_mandatory_recovery.episode_id
        ),
        "post_mandatory_recovery_episode_day": int(
            post_mandatory_recovery.episode_day
        ),
        "post_mandatory_recovery_holding_deficit": int(
            post_mandatory_recovery.holding_deficit
        ),
        "post_mandatory_recovery_exposure_deficit": float(
            post_mandatory_recovery.exposure_deficit
        ),
        "post_mandatory_recovery_max_new_names_today": int(
            post_mandatory_recovery.max_new_names_today
        ),
        "post_mandatory_recovery_max_buy_exposure_today": float(
            post_mandatory_recovery.max_buy_exposure_today
        ),
        "post_mandatory_recovery_deadline_sessions": int(
            post_mandatory_recovery.deadline_sessions
        ),
        "wealth_materiality_epsilon_amount": float(wealth_epsilon_amount),
        "planned_holding_count": int(plan.planned_holding_count),
        "holding_floor_violation_count": int(
            plan.holding_floor_violation_count
        ),
        "exposure_floor_violation": float(plan.exposure_floor_violation),
        "policy_holding_floor_violation_count": max(
            int(policy_band.holding_floor) - int(plan.planned_holding_count),
            0,
        ),
        "policy_floor_feasible_pre_optimizer": bool(
            deployment_bounds.policy_floor_feasible
        ),
        "atomic_pool_violation_count": int(
            plan.constraint_slacks.get("atomic_pool_violation_count", 0)
        ),
        "planned_effective_n": float(
            plan.constraint_slacks.get("planned_effective_n", 0.0)
        ),
        "effective_n_violation": float(
            plan.constraint_slacks.get("effective_n_violation", 0.0)
        ),
        "planned_pool_count": int(
            plan.constraint_slacks.get("planned_pool_count", 0)
        ),
        "pool_count_violation": int(
            plan.constraint_slacks.get("pool_count_violation", 0)
        ),
        "orphan_pool_recovery_active": bool(
            0
            < mandatory_projection.post_mandatory_holding_count
            < int(policy_band.minimum_active_pool_size)
            and post_mandatory_recovery.authorized
        ),
        "orphan_pool_breach": bool(
            0
            < int(plan.planned_holding_count)
            < int(policy_band.minimum_active_pool_size)
        ),
        "orphan_pool_recovery_deadline_breached": bool(
            0
            < int(plan.planned_holding_count)
            < int(policy_band.minimum_active_pool_size)
            and int(post_mandatory_recovery.episode_day)
            > int(post_mandatory_recovery.deadline_sessions)
        ),
        "proposal_contract": LEAN_PROPOSAL_CONTRACT,
        "action_proposal_count": int(len(proposals)),
        "action_plan_count": 1,
        "optimizer_invocation_count": 1,
        "optimizer_elapsed_seconds": float(optimizer_elapsed_seconds),
        "action_plan_id": plan.plan_id,
        "action_plan_selected_count": int(len(plan.selected_proposal_ids)),
        "action_plan_rejected_count": int(len(plan.rejected_proposals)),
        "selected_action_types": "|".join(selected_types),
        "lean_raw_entry_signal_count": len(raw_entry_signal_symbols),
        "lean_pre_cost_entry_shortlist_count": len(entry_shortlist),
        "candidate_pool_contract_version": CANDIDATE_POOL_CONTRACT_VERSION,
        "candidate_pool_runtime_state": candidate_pool_runtime_state,
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
        "selected_position_count": int(plan.selected_position_count),
        "profit_coverage_ratio": float(plan.profit_coverage_ratio),
        "profit_coverage_probability_lower": float(
            plan.profit_coverage_probability_lower
        ),
        "coverage_evidence_name_count": int(
            plan.coverage_evidence_name_count
        ),
        "expected_positive_pnl_amount": float(
            plan.expected_positive_pnl_amount
        ),
        "expected_loss_pnl_amount": float(plan.expected_loss_pnl_amount),
        "lifecycle_cost_amount": float(plan.lifecycle_cost_amount),
        "coverage_penalty_amount": float(plan.coverage_penalty_amount),
        "expected_log_growth": float(plan.expected_log_growth),
        "minimum_selected_marginal_utility_amount": float(
            plan.minimum_selected_marginal_utility_amount
        ),
        "maximum_rejected_marginal_utility_amount": float(
            plan.maximum_rejected_marginal_utility_amount
        ),
        "coverage_state": str(plan.coverage_state),
        "coverage_mode": str(plan.coverage_mode),
        "hold_baseline_objective_amount": float(
            plan.hold_baseline_objective_amount
        ),
        "incremental_expected_wealth_amount": float(
            plan.incremental_expected_wealth_amount
        ),
        "incremental_cvar_amount": float(plan.incremental_cvar_amount),
        "model_uncertainty_amount": float(plan.model_uncertainty_amount),
        "scenario_risk_penalty_amount": float(
            plan.scenario_risk_penalty_amount
        ),
        "scenario_evidence_state": str(plan.scenario_evidence_state),
        "scenario_contract_id": str(plan.scenario_contract_id),
        "scenario_risk_measure": str(plan.scenario_risk_measure),
        "joint_scenario_count": int(plan.joint_scenario_count),
        "best_rejected_proposal_ids": tuple(
            plan.best_rejected_proposal_ids
        ),
        "best_rejected_objective_amount": float(
            plan.best_rejected_objective_amount
        ),
        "best_rejected_expected_wealth_amount": float(
            plan.best_rejected_expected_wealth_amount
        ),
        "best_rejected_cvar_amount": float(
            plan.best_rejected_cvar_amount
        ),
        "best_rejected_model_uncertainty_amount": float(
            plan.best_rejected_model_uncertainty_amount
        ),
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
        "lean_replacement_requested": bool(context.active_replacement_enabled),
        "lean_replacement_reachable": False,
        "lean_replacement_status": (
            "requested_but_fail_closed_no_atomic_pair_factory"
            if bool(context.active_replacement_enabled)
            else "disabled_by_profile"
        ),
        "held_symbol_missing_candidate_count": int(
            len(set(current_lots) - set(rows))
        ),
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
        held_lots = max(int(current_lots.get(symbol, 1)), 1)
        rule = trading_rule_for(symbol, trade_date=context.decision_date)
        shares = float(held_lots * rule.minimum_buy_quantity)
        price = _number(row.get("close_nominal", row.get("close")))
        market_notional = max(price * shares, 0.0)
        sell_cost = single_side_cost_amount(
            symbol=symbol,
            side="sell",
            price=price,
            shares=shares,
            trade_date=context.decision_date,
            cost_profile=context.execution_cost_profile,
        )
        sell_release = sell_cash_released_amount(
            symbol=symbol,
            price=price,
            shares=shares,
            trade_date=context.decision_date,
            cost_profile=context.execution_cost_profile,
        )
        proposal = _proposal(
            context,
            symbol=symbol,
            action_type="safety_exit",
            lots=held_lots,
            expected=0.0,
            robust=0.0,
            downside=0.0,
            cost=sell_cost,
            funding=0.0,
            market_notional=market_notional,
            sell_cash_released=sell_release,
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
    lot_market_notional=None,
) -> None:
    if lot_market_notional is None:
        lot_market_notional = max(float(lot_cash), 0.0)
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
        current_position_lots = max(
            int(
                dict(
                    getattr(context, "current_lots_by_symbol", None) or {}
                ).get(symbol, round(old_weight / max(lot_weight, 1e-12)))
            ),
            1,
        )
        rule = trading_rule_for(symbol, trade_date=context.decision_date)
        current_shares = float(current_position_lots * rule.minimum_buy_quantity)
        price = _number(row.get("close_nominal", row.get("close")))
        position_market_notional = max(price * current_shares, 0.0)
        sell_cost = single_side_cost_amount(
            symbol=symbol,
            side="sell",
            price=price,
            shares=current_shares,
            trade_date=context.decision_date,
            cost_profile=context.execution_cost_profile,
        )
        sell_release = sell_cash_released_amount(
            symbol=symbol,
            price=price,
            shares=current_shares,
            trade_date=context.decision_date,
            cost_profile=context.execution_cost_profile,
        )
        proposal = _proposal(
            context,
            symbol=symbol,
            action_type=action_type,
            lots=current_position_lots,
            expected=robust,
            robust=robust,
            downside=0.0,
            cost=sell_cost,
            funding=0.0,
            market_notional=position_market_notional,
            sell_cash_released=sell_release,
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
        inferred_price = lot_market_notional / lot_shares
        exact_total_cost = round_trip_cost_amount(
            symbol=symbol,
            price=inferred_price,
            shares=lot_shares * add_lots,
            trade_date=decision_date,
            cost_profile=context.execution_cost_profile,
        )
        lifecycle_cost = estimate_lifecycle_cost(
            symbol=symbol,
            price=inferred_price,
            shares=lot_shares * add_lots,
            trade_date=decision_date,
            cost_profile=context.execution_cost_profile,
            # This proposal is the add leg itself; do not recursively charge
            # another expected add on top of the factual add lifecycle.
            expected_add_probability=0.0,
        )
        one_lot_cost = max(
            _number(row.get("scap_estimated_total_cost_amount")),
            0.0,
        )
        gross_robust_profit = (
            max(base_utility, 0.0) + one_lot_cost
        ) * add_lots
        scaled_base_utility = (
            gross_robust_profit - lifecycle_cost.total_lifecycle_cost_amount
        )
        if scaled_base_utility <= 0.0:
            return
        scaled_robust = scaled_base_utility
        add_buy_cash = buy_cash_required_amount(
            symbol=symbol,
            price=inferred_price,
            shares=lot_shares * add_lots,
            trade_date=decision_date,
            cost_profile=context.execution_cost_profile,
        )
        profile = dict(context.execution_cost_profile or {})
        economic_assessment = (
            assess_economic_order(
                market_notional_amount=lot_market_notional * add_lots,
                lifecycle_cost=lifecycle_cost,
                conservative_gross_profit_amount=gross_robust_profit,
                robust_net_profit_amount=scaled_robust,
                cost_profile=profile,
                high_confidence_exception=bool(current_authority_tier == "A"),
            )
            if bool(profile.get("scap_economic_order_contract_enabled", False))
            else None
        )
        proposal = _proposal(
            context,
            symbol=symbol,
            action_type="winner_add",
            lots=add_lots,
            expected=scaled_base_utility,
            robust=scaled_robust,
            downside=lot_cash * 0.15 * add_lots,
            cost=exact_total_cost,
            funding=add_buy_cash,
            market_notional=lot_market_notional * add_lots,
            buy_cash_required=add_buy_cash,
            suffix=f"winner_add_{layer + 1}",
            source="position_lifecycle_evidence",
            authority_tier=current_authority_tier,
            authority_snapshot_id=authority_snapshot_id,
            thesis=str(row.get("entry_thesis", "") or ""),
            hard_veto_reasons=(
                ("economic_order:" + economic_assessment.reason,)
                if economic_assessment is not None
                and not economic_assessment.passed
                else ()
            ),
            lifecycle_cost_amount=lifecycle_cost.total_lifecycle_cost_amount,
            round_trip_cost_ratio=lifecycle_cost.round_trip_cost_ratio,
            lifecycle_cost_to_gross_profit_ratio=(
                economic_assessment.lifecycle_cost_to_gross_profit_ratio
                if economic_assessment is not None
                else 0.0
            ),
            minimum_economic_order_amount=(
                economic_assessment.minimum_economic_order_amount
                if economic_assessment is not None
                else 0.0
            ),
            economic_order_pass=(
                economic_assessment.passed
                if economic_assessment is not None
                else True
            ),
            economic_order_reason=(
                economic_assessment.reason
                if economic_assessment is not None
                else "contract_disabled"
            ),
            allocation_sleeve="core_winner",
        )
        proposals.append(proposal)
        proposal_rows[proposal.proposal_id] = row
    lifecycle_loser_allowed = (
        bool(row.get("add_allowed", False))
        and str(row.get("add_decision_type", "")) == "loser_averaging"
        and bool(row.get("loser_averaging", False))
        and current_authority_tier in {"A", "B", "C"}
        and bool(authority_snapshot_id)
    )
    if (
        context.loser_add_enabled
        and lifecycle_loser_allowed
        and base_utility > 0.0
        and -0.10 <= unrealized <= -0.04
        and layer < 1
    ):
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
            market_notional=lot_market_notional,
            buy_cash_required=lot_cash,
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
    market_notional=0.0,
    buy_cash_required=0.0,
    sell_cash_released=0.0,
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
    hard_veto_reasons=(),
    lifecycle_cost_amount=0.0,
    round_trip_cost_ratio=0.0,
    lifecycle_cost_to_gross_profit_ratio=0.0,
    minimum_economic_order_amount=0.0,
    economic_order_pass=True,
    economic_order_reason="not_applicable",
    economic_order_warnings=(),
    p_win_lower=0.0,
    avg_win_return=0.0,
    avg_loss_return=0.0,
    expected_positive_pnl_amount=0.0,
    expected_loss_pnl_amount=0.0,
    coverage_evidence_authorized=False,
    allocation_sleeve="not_applicable",
    calibration_evidence_state="unavailable",
    calibration_effective_sample_size=0.0,
    scenario_contract_id="",
    decision_return_basis="legacy_unknown",
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
        cash_release_amount=max(float(sell_cash_released), 0.0),
        market_notional_amount=max(float(market_notional), 0.0),
        buy_cash_required_amount=max(float(buy_cash_required), 0.0),
        sell_cash_released_amount=max(float(sell_cash_released), 0.0),
        exposure_delta=(
            -float(context.current_weights.get(symbol, 0.0))
            if action_type in {"exit", "hard_exit", "safety_exit", "replacement_sell"}
            else float(market_notional) / max(float(context.nav_amount), 1e-12)
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
        hard_veto_reasons=tuple(str(value) for value in hard_veto_reasons),
        lifecycle_cost_amount=max(float(lifecycle_cost_amount), 0.0),
        round_trip_cost_ratio=max(float(round_trip_cost_ratio), 0.0),
        lifecycle_cost_to_gross_profit_ratio=max(
            float(lifecycle_cost_to_gross_profit_ratio), 0.0
        ),
        minimum_economic_order_amount=max(
            float(minimum_economic_order_amount), 0.0
        ),
        economic_order_pass=bool(economic_order_pass),
        economic_order_reason=str(economic_order_reason),
        economic_order_warnings=tuple(
            str(value) for value in economic_order_warnings
        ),
        p_win_lower=min(max(float(p_win_lower), 0.0), 1.0),
        avg_win_return=max(float(avg_win_return), 0.0),
        avg_loss_return=max(float(avg_loss_return), 0.0),
        expected_positive_pnl_amount=max(
            float(expected_positive_pnl_amount), 0.0
        ),
        expected_loss_pnl_amount=max(float(expected_loss_pnl_amount), 0.0),
        coverage_evidence_authorized=bool(coverage_evidence_authorized),
        allocation_sleeve=str(allocation_sleeve),
        calibration_evidence_state=str(calibration_evidence_state),
        calibration_effective_sample_size=max(
            float(calibration_effective_sample_size), 0.0
        ),
        scenario_contract_id=str(scenario_contract_id),
        decision_return_basis=str(decision_return_basis),
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


def _constructive_entry_exposure_bounds(
    *,
    proposals,
    current_lots,
    current_exposure: float,
    max_positions: int,
    available_cash: float,
    cash_buffer: float,
    strategic_budget: float,
) -> tuple[float, float]:
    """Build attainable signal and cash-feasible exposure without double counting.

    One smallest-lot positive, authority-eligible proposal is retained per new
    symbol.  Cash is deducted cumulatively and existing holdings consume the
    Web-supplied slots.  The result is deliberately constructive: every amount
    labelled integer-feasible corresponds to an explicit feasible sequence.
    """
    by_symbol: dict[str, ActionProposal] = {}
    for proposal in proposals:
        if (
            proposal.action_type != "new_entry"
            or proposal.symbol in current_lots
            or proposal.authority_tier not in {"A", "B", "C"}
            or proposal.hard_veto_reasons
            or (
                float(proposal.robust_net_profit_amount)
                - float(proposal.authority_penalty_amount)
            )
            <= 0.0
        ):
            continue
        incumbent = by_symbol.get(proposal.symbol)
        if incumbent is None or int(proposal.requested_lots) < int(
            incumbent.requested_lots
        ):
            by_symbol[proposal.symbol] = proposal
    candidates = sorted(
        by_symbol.values(),
        key=lambda item: (
            -float(item.unit_capital_robust_return),
            -float(item.robust_net_profit_amount),
            item.symbol,
        ),
    )
    slots = max(int(max_positions) - len(current_lots), 0)
    candidates = candidates[:slots]
    signal_increment = sum(max(float(item.exposure_delta), 0.0) for item in candidates)
    signal_supported = min(
        max(float(current_exposure), 0.0) + signal_increment,
        float(strategic_budget),
    )
    cash_remaining = max(float(available_cash) - float(cash_buffer), 0.0)
    feasible_increment = 0.0
    for item in candidates:
        required = max(float(item.buy_cash_required_amount), 0.0)
        if required <= cash_remaining + 1e-8:
            cash_remaining -= required
            feasible_increment += max(float(item.exposure_delta), 0.0)
    integer_feasible = min(
        max(float(current_exposure), 0.0) + feasible_increment,
        signal_supported,
    )
    return float(signal_supported), float(integer_feasible)


def _shrink_covariance(matrix: pd.DataFrame | None) -> tuple[pd.DataFrame | None, str]:
    if matrix is None or matrix.empty:
        return None, "fallback_thesis_caps"
    numeric = matrix.apply(pd.to_numeric, errors="coerce")
    if (
        numeric.shape[0] != numeric.shape[1]
        or list(numeric.index) != list(numeric.columns)
        or numeric.isna().any().any()
    ):
        return None, "fallback_thesis_caps"
    diagonal = pd.DataFrame(0.0, index=numeric.index, columns=numeric.columns)
    for symbol in numeric.index.intersection(numeric.columns):
        diagonal.at[symbol, symbol] = max(float(numeric.at[symbol, symbol]), 0.0)
    dimension = max(int(numeric.shape[0]), 1)
    shrinkage = min(max(dimension / 60.0, 0.10), 0.90)
    shrunk = (1.0 - shrinkage) * numeric + shrinkage * diagonal
    return (shrunk + shrunk.T) / 2.0, "adaptive_diagonal_shrinkage"


def _number(value, default: float = 0.0) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(numeric) if pd.notna(numeric) and math.isfinite(float(numeric)) else float(default)
