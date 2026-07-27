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
from functions.decision_council.integer_action_optimizer import (
    optimize_action_proposals,
)
from functions.decision_council.scap_v2_contracts import (
    ActionPlan,
    ActionProposal,
    ExposureAuthorization,
)


LEAN_VERSION = "small_capital_aggressive_profit_v3_lean"
LEAN_PROPOSAL_CONTRACT = "scap_v3_lean_proposal_factory_v1"


@dataclass(frozen=True)
class LeanDecision:
    proposals: tuple[ActionProposal, ...]
    plan: ActionPlan
    authorization: ExposureAuthorization
    proposal_rows: dict[str, pd.Series]
    diagnostics: dict


def build_lean_decision(context, candidates: pd.DataFrame) -> LeanDecision:
    """Build all actions first, then invoke the integer optimizer once."""
    data = candidates.copy()
    data["symbol"] = data["symbol"].astype(str)
    rows = {
        str(row["symbol"]): row
        for _, row in data.drop_duplicates("symbol", keep="last").iterrows()
    }
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
        if old_weight > 0.0 and lot_weight > 0.0:
            current_lots[symbol] = max(int(round(old_weight / lot_weight)), 1)

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
        decision_return = _number(row.get("scap_decision_expected_return"))
        point_return = _number(
            row.get("scap_expected_return_point", decision_return)
        )
        hard_vetoes = _entry_hard_vetoes(row, lot_cash, lot_weight)
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
        max_lots = min(max(max_by_name, 0), max(max_by_cash, 0), 4)
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
            )
            concentration_penalty = max(
                lots * lot_weight - 0.30, 0.0
            ) * float(context.nav_amount) * 0.01
            risk_penalty = _number(row.get("scap_risk_penalty_amount")) * lots
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
            )
            proposals.append(proposal)
            proposal_rows[proposal.proposal_id] = row
            symbol_has_positive_plan = (
                symbol_has_positive_plan or robust_profit > 0.0
            )
        if symbol_has_positive_plan:
            positive_signal_weights.append(lot_weight)

    current_exposure = min(sum(current_weights.values()), 1.0)
    strategic_budget = min(max(float(context.safety.exposure_cap), 0.0), 1.0)
    planned_safety_sell_weight = _append_exposure_cap_safety_exits(
        proposals,
        proposal_rows,
        context=context,
        rows=rows,
        current_weights=current_weights,
        current_lots=current_lots,
        current_exposure=current_exposure,
        strategic_budget=strategic_budget,
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
    covariance, covariance_state = _shrink_covariance(context.covariance_matrix)
    authorization = ExposureAuthorization(
        decision_id=str(context.decision_id),
        nav_amount=max(float(context.nav_amount), 1e-12),
        risk_exposure_ceiling=strategic_budget,
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
        new_entry_allowed=not bool(context.safety.hard_freeze_active),
        add_allowed=not bool(context.safety.hard_freeze_active),
        replacement_allowed=bool(context.active_replacement_enabled),
        current_cash_amount=max(float(context.cash_amount), 0.0),
        strategic_exposure_budget=strategic_budget,
        signal_supported_exposure=signal_supported,
        integer_feasible_exposure=integer_feasible,
        covariance_state=covariance_state,
        fallback_risk_model="thesis_and_per_name_stress_caps",
    )
    plan = optimize_action_proposals(
        proposals,
        authorization=authorization,
        current_lots_by_symbol=current_lots,
        current_weights_by_symbol=current_weights,
        current_exposure=current_exposure,
        max_positions=max(int(context.top_n), 1),
        thesis_by_symbol={
            symbol: str(row.get("cabinet_entry_thesis", "") or "")
            for symbol, row in rows.items()
        },
        max_names_per_thesis=2,
        correlation_matrix=covariance,
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
        "lean_slot_feasible_entry_count": len(proposal_entry_symbols),
        "lean_optimizer_selected_entry_count": len(selected_entry_symbols),
        "strategic_exposure_budget": strategic_budget,
        "signal_supported_exposure": signal_supported,
        "integer_feasible_exposure": integer_feasible,
        "planned_exposure": float(plan.projected_exposure),
        "signal_cash_drag": max(strategic_budget - signal_supported, 0.0),
        "lot_cash_drag": max(signal_supported - integer_feasible, 0.0),
        "covariance_state": covariance_state,
        "legacy_allocation_authority": "shadow_only",
        "unresolved_safety_exposure": max(
            current_exposure - planned_safety_sell_weight - strategic_budget,
            0.0,
        ),
        "planned_safety_sell_weight": planned_safety_sell_weight,
        "constraint_cash_reserve": float(authorization.cash_buffer_amount),
    }
    if diagnostics["optimizer_invocation_count"] != 1:
        raise RuntimeError("SCAP-V3 Lean optimizer invocation invariant failed")
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
) -> float:
    """Create factual full-position exits until the next-session cap is reachable."""
    required_reduction = max(float(current_exposure) - float(strategic_budget), 0.0)
    if required_reduction <= 1e-12:
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
        hard = any(
            token in exit_reason
            for token in ("qualification", "hard_stop", "loss_containment", "safety")
        )
        expected_hold = _number(row.get("comparable_expected_alpha"))
        position_amount = float(context.nav_amount) * old_weight
        robust = 0.0 if hard else max(-expected_hold * position_amount, 0.0)
        action_type = "hard_exit" if hard else "exit"
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
    unrealized = _number(
        row.get("net_unrealized_return", row.get("unrealized_return", 0.0))
    )
    layer = max(int(_number(row.get("add_layer"))) - 1, 0)
    base_utility = _number(row.get("add_expected_net_profit_lcb"))
    if context.winner_add_enabled and unrealized >= 0.0 and layer < 2:
        trigger = (0.04, 0.08)[min(layer, 1)]
        confirmation = 1.0 / (1.0 + math.exp(-(unrealized - trigger) / 0.02))
        robust = base_utility * confirmation
        proposal = _proposal(
            context,
            symbol=symbol,
            action_type="winner_add",
            lots=1,
            expected=max(base_utility, 0.0),
            robust=robust,
            downside=lot_cash * 0.15,
            cost=_number(row.get("scap_estimated_total_cost_amount")),
            funding=lot_cash,
            suffix=f"winner_add_{layer + 1}",
            source="position_lifecycle_evidence",
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
        exposure_delta=(
            -float(context.current_weights.get(symbol, 0.0))
            if action_type in {"exit", "hard_exit", "safety_exit", "replacement_sell"}
            else float(funding) / max(float(context.nav_amount), 1e-12)
        ),
    )


def _entry_hard_vetoes(row, lot_cash: float, lot_weight: float) -> tuple[str, ...]:
    reasons = []
    if lot_cash <= 0.0 or lot_weight <= 0.0:
        reasons.append("invalid_or_missing_lot_price")
    if lot_weight > 0.40 + 1e-12:
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
