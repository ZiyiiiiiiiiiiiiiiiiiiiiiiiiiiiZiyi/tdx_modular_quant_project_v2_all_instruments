"""Deterministic phase-one president policy."""
from __future__ import annotations

import pandas as pd

from config import GOVERNANCE_SINGLE_WEIGHT_DRIFT, GOVERNANCE_TOTAL_WEIGHT_DRIFT
from functions.decision_council.allocation import PortfolioConstructionCommittee
from functions.decision_council.active_replacement import choose_active_replacements
from functions.decision_council.contracts import DecisionContext
from functions.decision_council.exit_reason_contract import (
    EXIT_REASON_PRIORITY,
    canonical_exit_reason,
    is_full_liquidation_reason,
)
from functions.decision_council.integer_action_optimizer import (
    optimize_action_proposals,
)
from functions.decision_council.scap_v2_contracts import (
    ActionProposal,
    ExposureAuthorization,
)
from functions.decision_council.scap_v3_lean import build_lean_decision
from functions.decision_council.decision_arbitration import (
    arbitrate_position_actions,
    reconcile_same_symbol_orders,
)


ORDER_PRIORITIES = {
    "safety_deleveraging": 0,
    "qualification_exit": 1,
    "hard_stop_exit": 1,
    "profit_hard_stop_exit": 1,
    "loss_containment_exit": 1,
    "alpha_collapse_consensus": 2,
    "trend_break_exit": 3,
    "profit_giveback_exit": 3,
    "post_entry_failure_exit": 3,
    "signal_failure_exit": 3,
    "thesis_failure_exit": 3,
    "stale_time_exit": 3,
    "stale_time_reduce": 4,
    "volume_distribution_exit": 4,
    "replacement_opportunity_exit": 4,
    "replacement_opportunity_buy": 5,
    "loser_averaging_buy": 5,
    "winner_pyramiding_buy": 5,
    "single_name_risk_trim": 5,
    "normal_sell": 4,
    "normal_buy": 5,
    "exposure_catchup_buy": 5,
    "force_deploy_diversify_buy": 5,
    "force_deploy_defensive_buy": 6,
}
ORDER_PRIORITIES.update(EXIT_REASON_PRIORITY)
ORDER_COLUMNS = [
    "decision_id",
    "decision_date",
    "execution_date",
    "symbol",
    "side",
    "current_weight",
    "target_weight",
    "delta_weight",
    "reason",
    "priority",
    "pending_policy",
    "liquidation_intent",
    "position_state",
    "position_exit_reason",
    "add_layer",
    "add_allowed",
    "add_block_reason",
    "add_decision_type",
    "unified_action_selected",
    "unified_action_proposals",
    "unified_action_vetoed",
    "unified_action_conflict_count",
    "unified_action_contract",
    "action_plan_id",
    "action_proposal_id",
    "action_plan_selected",
    "action_plan_contract",
    "plan_hard_exposure_ceiling",
    "plan_target_exposure",
    "constraint_contract_version",
    "scap_v31_authority_tier",
    "scap_v31_authority_contract",
    "scap_candidate_utility",
    "add_expected_net_profit_lcb",
    "entry_matrix_score",
    "entry_alpha_score",
    "entry_timing_score",
    "entry_liquidity_score",
    "alpha_quality_score",
    "surge_capture_score",
    "follow_through_score",
    "exhaustion_score",
    "entry_success_probability",
    "entry_size_tier",
    "planned_entry_lots",
    "empirical_distribution_score",
    "final_entry_score",
    "tail_risk_proxy",
    "trend_direction_score",
    "peak_decay_score",
    "profit_protection_pressure",
    "dynamic_giveback_limit",
    "future_loss_risk_score",
    "downtrend_decay_score",
    "post_entry_failure_score",
    "orderflow_candidate_score",
    "reversal_entry_score",
    "breakout_gate_score",
    "trend_hold_score",
    "alpha_active_model_count",
    "alpha_active_module_count",
    "alpha_active_family_count",
    "alpha_max_active_module_share",
    "alpha_range_grid_vote_share",
    "entry_alpha_vote_count",
    "timing_filter_vote_count",
    "risk_override_vote_count",
    "liquidity_guard_vote_count",
    "hold_validation_vote_count",
    "sell_trigger_vote_count",
    "state_machine_role_pass",
    "state_machine_role_block_reason",
    "strategy_logic_version",
    "cabinet_native_final_score",
    "mainline_v3_score_authority",
    "mainline_v3_score_authority_version",
    "mainline_v3_selection_evaluated",
    "v31_reliability_score",
    "v31_reliability_score_coverage",
    "v31_reliability_contract",
    "v31_calibration_window",
    "v31_score_formula",
    "v31_score_authority",
    "v31_strict_entry_paper_only",
    "monthly_lgbm_raw_score",
    "monthly_lgbm_rank_percentile",
    "monthly_lgbm_model_month",
    "monthly_lgbm_trained_as_of",
    "monthly_lgbm_runtime_model",
    "hybrid_rule_rank_percentile",
    "hybrid_ml_rank_percentile",
    "hybrid_ml_weight",
    "hybrid_rule_weight",
    "hybrid_final_score",
    "hybrid_fusion_status",
    "hybrid_fusion_formula_version",
    "hybrid_score_authority",
    "cabinet_base_entry_score",
    "cabinet_strict_entry_score",
    "cabinet_proxy_entry_score",
    "cabinet_timing_score",
    "cabinet_liquidity_health_score",
    "cabinet_risk_safety_score",
    "cabinet_hold_support_score",
    "cabinet_entry_thesis",
    "cabinet_entry_thesis_support",
    "mainline_v3_one_lot_cash_required",
    "mainline_v3_one_lot_weight",
    "mainline_v3_lot_feasible",
    "comparable_value_horizon_days",
    "comparable_expected_alpha",
    "comparable_alpha_lcb",
    "comparable_value_contract",
    "replacement_pair_id",
    "replacement_paired_symbol",
    "replacement_pair_leg",
    "replacement_horizon_days",
    "replacement_expected_net_edge",
    "replacement_lcb_net_edge",
    "replacement_cost_rate",
    "replacement_contract",
]


class RulesBasedPresidentPolicy:
    """Convert ranked candidates and hard constraints into one daily plan."""

    def __init__(
        self,
        *,
        enable_sector_cap: bool = False,
        enable_safety_agent: bool = True,
        exit_mode: str = "full",
        risk_hard_gate_enabled: bool = False,
    ):
        self.enable_sector_cap = bool(enable_sector_cap)
        self.enable_safety_agent = bool(enable_safety_agent)
        self.exit_mode = str(exit_mode or "full").strip().lower()
        self.risk_hard_gate_enabled = bool(risk_hard_gate_enabled)
        self.portfolio_constructor = PortfolioConstructionCommittee(enable_sector_cap=enable_sector_cap)

    def decide(self, context: DecisionContext) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
        candidates = _prepare_candidates(context.candidates)
        if str(context.control_mode).strip().lower() == "aggressive_lean":
            return self._decide_scap_v3_lean(context, candidates)
        candidate_index = candidates.set_index("symbol", drop=False)
        locked_weights = {
            symbol: float(weight)
            for symbol, weight in context.current_weights.items()
            if symbol in context.pending_locked_symbols
        }
        safety_cap = float(context.safety.exposure_cap) if self.enable_safety_agent else 1.0
        eligible = candidates[~candidates["symbol"].isin(context.pending_locked_symbols)].copy()
        allocatable_cap = max(
            safety_cap - sum(locked_weights.values()),
            0.0,
        )
        held_symbols = []
        for symbol, days in context.holding_days.items():
            if symbol not in candidate_index.index or symbol in context.pending_locked_symbols:
                continue
            row = candidate_index.loc[symbol]
            if bool(row.get("exit_state", False)):
                continue
            if bool(row["alpha_collapse_exit"]):
                continue
            if (
                int(days) < int(context.minimum_holding_days)
                or int(row["candidate_rank"]) <= int(context.hold_rank_limit)
                or _holding_age_review_passed(row)
            ):
                held_symbols.append(symbol)
        ranked_symbols = eligible.loc[
            (eligible["candidate_rank"] <= int(context.entry_rank_limit))
            & eligible.get("entry_confirmed", pd.Series(True, index=eligible.index)).fillna(False).astype(bool)
            & eligible.apply(_state_machine_role_gate_pass, axis=1)
            & ~eligible.get("cooldown_active", pd.Series(False, index=eligible.index)).fillna(False).astype(bool)
            & ~eligible.get("exit_state", pd.Series(False, index=eligible.index)).fillna(False).astype(bool)
            & ~eligible.get("position_state", pd.Series("", index=eligible.index)).astype(str).str.lower().isin(
                {"blocked", "cooldown", "exiting", "protecting_profit"}
            )
        ].sort_values(["primary_score", "symbol"], ascending=[False, True])["symbol"].tolist()
        scap_discrete_symbols: set[str] = set()
        scap_exposure_pruned_count = 0
        if "scap_action_candidate" in eligible.columns or "scap_optimizer_selected" in eligible.columns:
            # SCAP admits candidates and values them in whole lots.  Preserve
            # that same unit through portfolio construction instead of letting
            # the continuous allocator shrink a selected lot below the order
            # drift threshold and the retail adapter later inflate it again.
            current_exposure = sum(
                max(float(weight), 0.0)
                for weight in context.current_weights.values()
            )
            incremental_cap = max(float(safety_cap) - current_exposure, 0.0)
            candidate_flag = (
                eligible["scap_action_candidate"].fillna(False).astype(bool)
                if "scap_action_candidate" in eligible.columns
                else eligible["scap_optimizer_selected"].fillna(False).astype(bool)
            )
            discrete_pool = eligible[
                eligible["symbol"].astype(str).isin(ranked_symbols)
                & ~eligible["symbol"].astype(str).isin(context.current_weights)
                & candidate_flag
            ].copy()
            scap_discrete_symbols = _select_scap_discrete_entries(
                discrete_pool,
                incremental_exposure_cap=incremental_cap,
                correlation_matrix=context.covariance_matrix,
            )
            scap_exposure_pruned_count = max(
                int(len(discrete_pool)) - int(len(scap_discrete_symbols)),
                0,
            )
            ranked_symbols = [
                symbol
                for symbol in ranked_symbols
                if symbol in context.current_weights or symbol in scap_discrete_symbols
            ]
            eligible["scap_optimizer_selected"] = eligible["symbol"].astype(str).isin(
                scap_discrete_symbols
            )
            eligible["scap_action_plan_authority"] = eligible[
                "scap_optimizer_selected"
            ].map({True: "selected", False: "not_selected"})
        selected_symbols = list(dict.fromkeys(held_symbols))
        # Every live position consumes a slot even when it is absent from today's
        # ranked candidate frame.  Counting only held_symbols allowed stale
        # positions to coexist with new buys above context.top_n.
        projected_position_symbols = {
            str(symbol)
            for symbol, weight in context.current_weights.items()
            if float(weight) > 1e-12
        }
        for symbol in ranked_symbols:
            if symbol in selected_symbols:
                continue
            if symbol in projected_position_symbols:
                selected_symbols.append(symbol)
                continue
            if len(projected_position_symbols) < int(context.top_n):
                selected_symbols.append(symbol)
                projected_position_symbols.add(symbol)
        selected = eligible[eligible["symbol"].isin(selected_symbols)].copy()
        selected = selected.sort_values(["primary_score", "symbol"], ascending=[False, True])
        allocated, allocation_diagnostics = self.portfolio_constructor.construct(
            selected,
            exposure_cap=allocatable_cap,
            covariance_matrix=context.covariance_matrix,
        )
        if self.risk_hard_gate_enabled:
            allocated, hard_gate_diagnostics = _apply_policy_risk_hard_gate(
                allocated,
                current_weights=context.current_weights,
                diagnostics=allocation_diagnostics,
            )
            allocation_diagnostics.update(hard_gate_diagnostics)
        if scap_discrete_symbols and not allocated.empty:
            allocated_symbols = allocated["symbol"].astype(str)
            for symbol, weight in context.current_weights.items():
                held_mask = allocated_symbols.eq(str(symbol))
                if held_mask.any():
                    allocated.loc[held_mask, "target_weight"] = max(float(weight), 0.0)
            discrete_mask = allocated_symbols.isin(scap_discrete_symbols)
            discrete_weights = pd.to_numeric(
                allocated.loc[discrete_mask, "mainline_v3_one_lot_weight"],
                errors="coerce",
            ).fillna(0.0)
            allocated.loc[discrete_mask, "target_weight"] = discrete_weights
        allocation_diagnostics.update(
            {
                "scap_discrete_entry_count": int(len(scap_discrete_symbols)),
                "scap_exposure_cap_pruned_count": int(scap_exposure_pruned_count),
                "scap_discrete_entry_weight": float(
                    pd.to_numeric(
                        allocated.loc[
                            allocated["symbol"].astype(str).isin(scap_discrete_symbols),
                            "target_weight",
                        ],
                        errors="coerce",
                    ).fillna(0.0).sum()
                ) if not allocated.empty else 0.0,
            }
        )
        target_weights = dict(zip(allocated["symbol"], allocated["target_weight"]))
        target_weights.update(locked_weights)
        active_current_weights = {
            str(symbol): float(weight) for symbol, weight in context.current_weights.items()
        }
        replacement_pairs = (
            choose_active_replacements(
                eligible,
                current_weights=active_current_weights,
                holding_days={str(symbol): int(days) for symbol, days in context.holding_days.items()},
                decision_date=context.decision_date,
                minimum_holding_days=context.minimum_holding_days,
                max_pairs_per_day=context.active_replacement_max_pairs_per_day,
            )
            if context.active_replacement_enabled
            else []
        )
        for pair in replacement_pairs:
            target_weights[pair.held_symbol] = 0.0
            challenger = candidate_index.loc[pair.challenger_symbol]
            one_lot_weight = pd.to_numeric(
                pd.Series([challenger.get("mainline_v3_one_lot_weight")]), errors="coerce"
            ).iloc[0]
            target_weights[pair.challenger_symbol] = (
                float(one_lot_weight)
                if pd.notna(one_lot_weight) and float(one_lot_weight) > 0.0
                else max(float(active_current_weights.get(pair.held_symbol, 0.0)), 1e-6)
            )
        ideal = self._ideal_plan(context, allocated, locked_weights, allocation_diagnostics)
        replacement_edge = _best_replacement_edge(eligible, set(context.current_weights))
        orders, order_diagnostics = self._build_orders(
            context,
            target_weights,
            eligible,
            safety_cap,
            replacement_edge,
            replacement_pairs=replacement_pairs,
            risk_catchup_block=bool(allocation_diagnostics.get("risk_catchup_block_applied", False)),
        )
        diagnostics = {
            **allocation_diagnostics,
            **order_diagnostics,
            "locked_nominal_weight": sum(locked_weights.values()),
            "preserved_unranked_nominal_weight": 0.0,
            "target_exposure": sum(target_weights.values()),
            "active_replacement_enabled": bool(context.active_replacement_enabled),
            "sector_cap_enabled": self.enable_sector_cap,
            "safety_agent_enabled": self.enable_safety_agent,
        }
        return ideal, orders, diagnostics

    def _decide_scap_v3_lean(self, context, candidates):
        """Bypass legacy selection/allocation and consume one integer plan."""
        decision = build_lean_decision(context, candidates)
        candidate_index = candidates.set_index("symbol", drop=False)
        proposals = {
            proposal.proposal_id: proposal for proposal in decision.proposals
        }
        rows = []
        for proposal_id in decision.plan.selected_proposal_ids:
            proposal = proposals[proposal_id]
            symbol = proposal.symbol
            row = (
                candidate_index.loc[symbol]
                if symbol in candidate_index.index
                else None
            )
            old = float(context.current_weights.get(symbol, 0.0))
            lot_weight = (
                _safe_row_float(row, "mainline_v3_one_lot_weight", 0.0)
                if row is not None
                else 0.0
            )
            if proposal.action_type in {"exit", "hard_exit", "safety_exit"}:
                new = 0.0
                candidate_reason = (
                    str(row.get("position_exit_reason", "") or "")
                    if row is not None
                    else ""
                )
                if proposal.action_type == "safety_exit":
                    reason = "safety_deleveraging"
                else:
                    reason = (
                        candidate_reason
                        if candidate_reason in ORDER_PRIORITIES
                        else "normal_sell"
                    )
            elif proposal.action_type == "winner_add":
                new = old + max(float(proposal.exposure_delta), 0.0)
                reason = "winner_pyramiding_buy"
            elif proposal.action_type == "loser_add":
                new = old + max(float(proposal.exposure_delta), 0.0)
                reason = "loser_averaging_buy"
            elif proposal.action_type == "replacement_buy":
                new = old + max(float(proposal.exposure_delta), 0.0)
                reason = "replacement_opportunity_buy"
            else:
                new = max(float(proposal.exposure_delta), 0.0)
                reason = (
                    "exposure_catchup_buy"
                    if bool(
                        decision.diagnostics.get(
                            "post_mandatory_recovery_authorized",
                            False,
                        )
                    )
                    and not bool(context.allow_normal_rebalance)
                    else "normal_buy"
                )
            order = self._order_row(
                context,
                symbol,
                old,
                min(max(new, 0.0), float(context.per_name_structural_cap)),
                reason,
                row,
            )
            order["action_plan_id"] = decision.plan.plan_id
            order["action_proposal_id"] = proposal.proposal_id
            order["action_plan_selected"] = True
            order["action_plan_contract"] = decision.plan.contract_version
            order["plan_hard_exposure_ceiling"] = float(
                decision.authorization.hard_exposure_ceiling
            )
            order["plan_target_exposure"] = float(
                decision.authorization.desired_exposure_target
            )
            order["constraint_contract_version"] = str(
                decision.plan.contract_version
            )
            order["unified_action_selected"] = proposal.action_type
            order["unified_action_contract"] = "scap_v3_lean_single_plan_v1"
            order["planned_entry_lots"] = int(proposal.requested_lots)
            order["scap_v31_authority_tier"] = proposal.authority_tier
            order["scap_v31_authority_contract"] = str(
                row.get("scap_v31_authority_contract", "")
                if row is not None
                else ""
            )
            if proposal.action_type in {"winner_add", "loser_add"}:
                order["add_allowed"] = True
                order["add_decision_type"] = proposal.action_type
                order["add_block_reason"] = "selected_by_unique_action_plan"
            rows.append(order)
        orders = pd.DataFrame(rows, columns=ORDER_COLUMNS)
        ideal = orders[
            [
                column
                for column in (
                    "decision_id",
                    "decision_date",
                    "symbol",
                    "target_weight",
                    "action_plan_id",
                    "action_proposal_id",
                )
                if column in orders.columns
            ]
        ].copy()
        diagnostics = dict(decision.diagnostics)
        selected_ids = set(decision.plan.selected_proposal_ids)
        rejection_by_id = {
            str(item.get("proposal_id", "")): str(item.get("reason", ""))
            for item in decision.plan.rejected_proposals
        }
        from functions.decision_council.exposure_contract import build_record_lineage

        diagnostics["_action_proposal_rows"] = [
            {
                **proposal.as_dict(),
                **build_record_lineage(
                    decision_id=proposal.decision_id,
                    record_stage="candidate_economic_assessment",
                    record_id=proposal.proposal_id,
                    immutable_payload=proposal.as_dict(),
                    formula_version=str(proposal.contract_version),
                ),
                "decision_date": pd.Timestamp(context.decision_date),
                "selected_by_plan": proposal.proposal_id in selected_ids,
                "optimizer_rejection_reason": rejection_by_id.get(
                    proposal.proposal_id,
                    "",
                ),
                "action_plan_id": decision.plan.plan_id,
            }
            for proposal in decision.proposals
        ]
        diagnostics["_action_plan_rows"] = [
            {
                **{
                    key: value
                    for key, value in decision.plan.as_dict().items()
                    if key != "rejected_proposals"
                },
                "rejected_proposal_count": len(
                    decision.plan.rejected_proposals
                ),
                "rejected_proposal_ids": tuple(
                    str(item.get("proposal_id", ""))
                    for item in decision.plan.rejected_proposals
                ),
                "rejected_detail_storage": "governance_action_proposal_ledger",
                **build_record_lineage(
                    decision_id=decision.plan.decision_id,
                    record_stage="portfolio_action_plan",
                    record_id=decision.plan.plan_id,
                    immutable_payload=decision.plan.as_dict(),
                    formula_version=str(decision.plan.contract_version),
                ),
                "decision_date": pd.Timestamp(context.decision_date),
                "authority_snapshot_id": (
                    decision.authorization.authority_snapshot_id
                ),
                "hard_exposure_ceiling": (
                    decision.authorization.hard_exposure_ceiling
                ),
                "desired_exposure_target": (
                    decision.authorization.desired_exposure_target
                ),
                "confirmed_derisk_target": (
                    decision.authorization.confirmed_derisk_target
                ),
            }
        ]
        diagnostics.update(
            {
                "target_exposure": float(
                    decision.authorization.desired_exposure_target
                ),
                "optimizer_planned_exposure": float(
                    decision.plan.projected_exposure
                ),
                "effective_target_exposure_cap": float(
                    decision.authorization.risk_exposure_ceiling
                ),
                "action_plan_expected_net_profit_amount": float(
                    decision.plan.expected_net_profit_amount
                ),
                "action_plan_robust_net_profit_amount": float(
                    decision.plan.robust_net_profit_amount
                ),
                "action_plan_downside_cvar_amount": float(
                    decision.plan.downside_cvar_amount
                ),
                "action_plan_solver_status": decision.plan.solver_status,
                "action_plan_rejection_lineage": "|".join(
                    f"{item.get('proposal_id')}:{item.get('reason')}"
                    for item in decision.plan.rejected_proposals
                ),
                "scap_discrete_entry_count": int(
                    sum(
                        proposal.action_type == "new_entry"
                        for proposal in decision.proposals
                        if proposal.proposal_id
                        in set(decision.plan.selected_proposal_ids)
                    )
                ),
            }
        )
        return ideal, orders, diagnostics

    def _ideal_plan(self, context, allocated, locked_weights, diagnostics):
        columns = [
            "decision_id",
            "decision_date",
            "horizon_days",
            "symbol",
            "ideal_weight",
            "alpha_percentile",
            "expected_return_5d",
            "aggregate_confidence",
            "hold_until_date",
            "proposal_sources",
            "prototype_sector",
            "constraint_cash_reserve",
            "p_win_5d_calibrated",
            "p_win_10d_calibrated",
            "p_win_10d_wilson_lower",
            "expected_edge_5d",
            "expected_edge_10d",
            "conservative_expected_edge_10d",
            "edge_to_risk_10d",
            "conservative_edge_to_risk_10d",
            "entry_evidence_grade",
            "entry_confirmed",
            "entry_block_reason",
            "entry_matrix_score",
            "entry_alpha_score",
            "entry_timing_score",
            "entry_liquidity_score",
            "alpha_quality_score",
            "surge_capture_score",
            "follow_through_score",
            "exhaustion_score",
            "entry_success_probability",
            "entry_size_tier",
            "planned_entry_lots",
            "downtrend_decay_score",
            "post_entry_failure_score",
            "entry_quality_tier",
            "candidate_pool_flag",
            "watchlist_flag",
            "direct_buy_flag",
            "trend_stability_score",
            "volume_health_score",
            "drawdown_quality_score",
            "position_state",
            "exit_state",
            "position_exit_reason",
            "paper_exit_reason",
            "paper_exit_state",
            "cooldown_active",
            "paper_cooldown_active",
            "cooldown_until",
            "add_allowed",
            "add_block_reason",
            "add_layer",
            "orderflow_candidate_score",
            "reversal_entry_score",
            "breakout_gate_score",
            "trend_hold_score",
            "module_candidate_score",
            "module_entry_score",
            "module_hold_score",
            "alpha_active_model_count",
            "alpha_active_module_count",
            "alpha_active_family_count",
            "alpha_max_active_module_share",
            "alpha_range_grid_vote_share",
            "entry_alpha_vote_count",
            "timing_filter_vote_count",
            "risk_override_vote_count",
            "liquidity_guard_vote_count",
            "hold_validation_vote_count",
            "sell_trigger_vote_count",
            "state_machine_role_pass",
            "state_machine_role_block_reason",
            "orderflow_candidate_pass",
            "reversal_confirm_pass",
            "breakout_gate_pass",
            "paper_alpha_collapse_exit",
            "strategy_logic_version",
            "cabinet_native_final_score",
            "v31_reliability_score",
            "v31_reliability_score_coverage",
            "v31_reliability_contract",
            "v31_calibration_window",
            "v31_score_formula",
            "v31_score_authority",
            "v31_strict_entry_paper_only",
            "cabinet_base_entry_score",
            "cabinet_strict_entry_score",
            "cabinet_proxy_entry_score",
            "cabinet_timing_score",
            "cabinet_liquidity_health_score",
            "cabinet_risk_safety_score",
            "cabinet_hold_support_score",
            "cabinet_entry_thesis",
            "cabinet_entry_thesis_support",
            "mainline_v3_one_lot_cash_required",
            "mainline_v3_one_lot_weight",
            "mainline_v3_lot_feasible",
        ]
        plan = allocated.copy()
        if not plan.empty:
            plan["ideal_weight"] = plan["target_weight"]
            plan["decision_id"] = context.decision_id
            plan["decision_date"] = context.decision_date
            plan["horizon_days"] = 5
            plan["hold_until_date"] = pd.Timestamp(context.decision_date) + pd.offsets.BDay(context.minimum_holding_days)
            plan["proposal_sources"] = plan.get("proposal_sources", "alpha_ensemble")
            plan["constraint_cash_reserve"] = diagnostics["constraint_cash_reserve"]
        for column in columns:
            if column not in plan.columns:
                plan[column] = pd.NA
        plan = plan[columns].copy()
        locked_rows = []
        for symbol, weight in locked_weights.items():
            locked_rows.append(
                {
                    "decision_id": context.decision_id,
                    "decision_date": context.decision_date,
                    "horizon_days": 5,
                    "symbol": symbol,
                    "ideal_weight": weight,
                    "alpha_percentile": pd.NA,
                    "expected_return_5d": pd.NA,
                    "aggregate_confidence": pd.NA,
                    "hold_until_date": pd.NA,
                    "proposal_sources": "pending_locked",
                    "prototype_sector": pd.NA,
                    "constraint_cash_reserve": diagnostics["constraint_cash_reserve"],
                    "p_win_5d_calibrated": pd.NA,
                    "p_win_10d_calibrated": pd.NA,
                    "p_win_10d_wilson_lower": pd.NA,
                    "expected_edge_5d": pd.NA,
                    "expected_edge_10d": pd.NA,
                    "conservative_expected_edge_10d": pd.NA,
                    "edge_to_risk_10d": pd.NA,
                    "conservative_edge_to_risk_10d": pd.NA,
                    "entry_evidence_grade": pd.NA,
                    "entry_confirmed": pd.NA,
                    "entry_block_reason": "pending_locked",
                    "entry_matrix_score": pd.NA,
                    "entry_alpha_score": pd.NA,
                    "entry_timing_score": pd.NA,
                    "entry_liquidity_score": pd.NA,
                    "alpha_quality_score": pd.NA,
                    "surge_capture_score": pd.NA,
                    "follow_through_score": pd.NA,
                    "exhaustion_score": pd.NA,
                    "entry_success_probability": pd.NA,
                    "entry_size_tier": pd.NA,
                    "planned_entry_lots": pd.NA,
                    "downtrend_decay_score": pd.NA,
                    "post_entry_failure_score": pd.NA,
                    "entry_quality_tier": pd.NA,
                    "candidate_pool_flag": pd.NA,
                    "watchlist_flag": pd.NA,
                    "direct_buy_flag": pd.NA,
                    "trend_stability_score": pd.NA,
                    "volume_health_score": pd.NA,
                    "drawdown_quality_score": pd.NA,
                    "position_state": "pending_locked",
                    "exit_state": False,
                    "position_exit_reason": "",
                    "paper_exit_reason": "",
                    "paper_exit_state": False,
                    "cooldown_active": False,
                    "paper_cooldown_active": False,
                    "cooldown_until": pd.NA,
                    "add_allowed": False,
                    "add_block_reason": "pending_locked",
                    "add_layer": pd.NA,
                    "orderflow_candidate_score": pd.NA,
                    "reversal_entry_score": pd.NA,
                    "breakout_gate_score": pd.NA,
                    "trend_hold_score": pd.NA,
                    "module_candidate_score": pd.NA,
                    "module_entry_score": pd.NA,
                    "module_hold_score": pd.NA,
                    "alpha_active_model_count": pd.NA,
                    "alpha_active_module_count": pd.NA,
                    "alpha_active_family_count": pd.NA,
                    "alpha_max_active_module_share": pd.NA,
                    "alpha_range_grid_vote_share": pd.NA,
                    "entry_alpha_vote_count": pd.NA,
                    "timing_filter_vote_count": pd.NA,
                    "risk_override_vote_count": pd.NA,
                    "liquidity_guard_vote_count": pd.NA,
                    "hold_validation_vote_count": pd.NA,
                    "sell_trigger_vote_count": pd.NA,
                    "state_machine_role_pass": False,
                    "state_machine_role_block_reason": "pending_locked",
                    "orderflow_candidate_pass": pd.NA,
                    "reversal_confirm_pass": pd.NA,
                    "breakout_gate_pass": pd.NA,
                    "paper_alpha_collapse_exit": pd.NA,
                }
            )
        if locked_rows and plan.empty:
            keep = pd.DataFrame(locked_rows)
        elif locked_rows:
            locked = pd.DataFrame(locked_rows)
            keep = pd.concat(
                [plan.dropna(axis=1, how="all"), locked.dropna(axis=1, how="all")],
                ignore_index=True,
            )
        else:
            keep = plan
        for column in columns:
            if column not in keep.columns:
                keep[column] = pd.NA
        return keep[columns].copy()

    def _build_orders(self, context, target_weights, eligible, safety_cap, replacement_edge: float, *, replacement_pairs=(), risk_catchup_block: bool = False):
        current = {str(symbol): float(weight) for symbol, weight in context.current_weights.items()}
        symbols = sorted(set(current) | set(target_weights))
        safety_shortfall = max(sum(current.values()) - float(safety_cap), 0.0)
        rows = []
        sell_symbols = set()
        normal_turnover = 0.0
        total_drift = sum(abs(target_weights.get(symbol, 0.0) - current.get(symbol, 0.0)) for symbol in symbols)
        candidate_index = eligible.set_index("symbol", drop=False)
        pair_sell = {pair.held_symbol: pair for pair in replacement_pairs}
        pair_buy = {pair.challenger_symbol: pair for pair in replacement_pairs}
        safety_sold_symbols = set()
        remaining_safety_shortfall = safety_shortfall
        safety_ranked = sorted(
            (
                (
                    float(candidate_index.at[symbol, "primary_score"]) if symbol in candidate_index.index else float("-inf"),
                    symbol,
                    weight,
                )
                for symbol, weight in current.items()
                if symbol not in context.pending_locked_symbols and float(weight) > 0.0
            ),
            key=lambda item: (item[0], item[1]),
        )
        for _, symbol, old in safety_ranked:
            if remaining_safety_shortfall <= 1e-12:
                break
            paired_replacement = pair_sell.get(symbol)
            sell_weight = float(old) if paired_replacement is not None else min(float(old), remaining_safety_shortfall)
            row = candidate_index.loc[symbol] if symbol in candidate_index.index else None
            reason = "replacement_opportunity_exit" if paired_replacement is not None else "safety_deleveraging"
            rows.append(self._order_row(context, symbol, old, old - sell_weight, reason, row))
            sell_symbols.add(symbol)
            safety_sold_symbols.add(symbol)
            remaining_safety_shortfall -= sell_weight
        for symbol in symbols:
            if symbol in context.pending_locked_symbols or symbol in safety_sold_symbols:
                continue
            old = current.get(symbol, 0.0)
            new = target_weights.get(symbol, 0.0)
            row = candidate_index.loc[symbol] if symbol in candidate_index.index else None
            if old > 1e-12 and row is not None and bool(row.get("stale_time_reduce", False)):
                new = min(float(new), float(old) * 0.50)
            delta = new - old
            if abs(delta) <= 1e-12:
                continue
            if symbol in pair_sell and delta < 0.0:
                reason = "replacement_opportunity_exit"
                new = 0.0
                delta = -old
            elif symbol in pair_buy and delta > 0.0:
                reason = "replacement_opportunity_buy"
            else:
                reason = _order_reason(symbol, delta, row, context, replacement_edge, exit_mode=self.exit_mode)
            is_confirmed_entry_buy = (
                delta > 0
                and old <= 1e-12
                and row is not None
                and bool(row.get("entry_confirmed", False))
                and _state_machine_role_gate_pass(row)
                and str(row.get("entry_size_tier", "")).strip().lower() in {
                    "basket_1_lot",
                    "diversify_1_lot",
                    "starter_1_lot",
                    "starter_2_lot",
                    "starter_strong",
                }
                and (
                    str(row.get("candidate_state", "")).strip().lower() == "entry_selected"
                    or str(row.get("position_state", "")).strip().lower() in {"building", "strong_building", "holding", "watching"}
                )
            )
            is_discrete_confirmed_entry = (
                is_confirmed_entry_buy
                and bool(row.get("scap_optimizer_selected", False))
                and pd.notna(row.get("mainline_v3_one_lot_weight"))
                and abs(
                    float(new)
                    - float(row.get("mainline_v3_one_lot_weight"))
                ) <= 1e-10
            )
            is_catchup_buy = (
                delta > 0
                and context.catchup_allowed
                and not bool(risk_catchup_block)
                and reason == "normal_buy"
                and old <= 1e-12
            )
            is_forced_sell = delta < 0 and reason in {
                "qualification_exit",
                "hard_stop_exit",
                "profit_hard_stop_exit",
                "loss_containment_exit",
                "alpha_collapse_consensus",
                "profit_giveback_exit",
                "post_entry_failure_exit",
                "signal_failure_exit",
                "thesis_failure_exit",
                "stale_time_exit",
                "stale_time_reduce",
            }
            is_active_replacement = reason in {"replacement_opportunity_exit", "replacement_opportunity_buy"}
            if not is_forced_sell and not is_active_replacement:
                # Normal construction is calendar-authorized; independently
                # authorized low-exposure recovery may execute between monthly
                # dates within its own daily budget.
                if (
                    not context.allow_normal_rebalance
                    and delta > 0
                    and not is_catchup_buy
                ):
                    continue
                if delta > 0 and safety_shortfall > 1e-12:
                    continue
                if delta > 0 and symbol in sell_symbols:
                    continue
                if delta > 0 and context.transition_only and not is_confirmed_entry_buy:
                    continue
                if delta > 0 and row is not None and str(row.get("position_state", "")).strip().lower() in {
                    "protecting_profit",
                    "exiting",
                    "cooldown",
                    "blocked",
                }:
                    continue
                if delta > 0 and old <= 1e-12 and row is not None and not _state_machine_role_gate_pass(row):
                    continue
                if delta > 0 and old > 1e-12 and row is not None and not bool(row.get("add_allowed", False)):
                    continue
                if delta < 0 and int(context.holding_days.get(symbol, 0)) < int(context.minimum_holding_days):
                    continue
                if (
                    not is_discrete_confirmed_entry
                    and abs(delta) < GOVERNANCE_SINGLE_WEIGHT_DRIFT
                    and total_drift < GOVERNANCE_TOTAL_WEIGHT_DRIFT
                ):
                    continue
                if is_discrete_confirmed_entry:
                    # The exposure-capped discrete subset is already the
                    # authoritative risk decision.  Partial adjustment and a
                    # continuous turnover bucket must not erase or resize it.
                    normal_turnover += abs(delta)
                else:
                    delta *= float(context.partial_adjustment_rate)
                    new = old + delta
                    if is_catchup_buy:
                        budget_limit = float(context.turnover_budget) + float(context.catchup_buy_budget)
                    elif is_confirmed_entry_buy:
                        budget_limit = max(float(context.turnover_budget), abs(float(delta)))
                    else:
                        budget_limit = float(context.turnover_budget)
                    allowed = max(budget_limit - normal_turnover, 0.0)
                    if allowed <= 1e-12:
                        continue
                    if abs(delta) > allowed:
                        delta = allowed if delta > 0 else -allowed
                        new = old + delta
                    normal_turnover += abs(delta)
            if delta < 0:
                sell_symbols.add(symbol)
            rows.append(self._order_row(context, symbol, old, new, reason, row))
        orders = pd.DataFrame(rows, columns=ORDER_COLUMNS)
        orders, action_conflicts = reconcile_same_symbol_orders(orders)
        if not orders.empty and replacement_pairs:
            for pair in replacement_pairs:
                sell_mask = orders["symbol"].astype(str).eq(pair.held_symbol) & orders["side"].astype(str).eq("sell")
                buy_mask = orders["symbol"].astype(str).eq(pair.challenger_symbol) & orders["side"].astype(str).eq("buy")
                # A buy without its funding sell is an invalid orphan.  Drop it
                # at the policy boundary instead of letting it expire later.
                if not bool(sell_mask.any() and buy_mask.any()):
                    orders = orders.loc[~buy_mask].copy()
                    continue
                for symbol, leg, paired in (
                    (pair.held_symbol, "sell", pair.challenger_symbol),
                    (pair.challenger_symbol, "buy", pair.held_symbol),
                ):
                    mask = orders["symbol"].astype(str).eq(symbol) & orders["side"].astype(str).eq(leg)
                    orders.loc[mask, "replacement_pair_id"] = pair.pair_id
                    orders.loc[mask, "replacement_paired_symbol"] = paired
                    orders.loc[mask, "replacement_pair_leg"] = leg
                    orders.loc[mask, "replacement_horizon_days"] = pair.horizon_days
                    orders.loc[mask, "replacement_expected_net_edge"] = pair.expected_net_edge
                    orders.loc[mask, "replacement_lcb_net_edge"] = pair.lcb_net_edge
                    orders.loc[mask, "replacement_cost_rate"] = pair.estimated_cost_rate
                    orders.loc[mask, "replacement_contract"] = "sell_fill_before_buy_same_session_v1"
        action_plan_diagnostics = {}
        if (
            not orders.empty
            and (
                "scap_action_candidate" in eligible.columns
                or "scap_candidate_utility" in eligible.columns
            )
        ):
            orders, action_plan_diagnostics = _apply_unique_action_plan(
                orders,
                context=context,
                candidates=eligible,
                safety_cap=safety_cap,
            )
        planned_safety_sell_weight = float(
            -orders.loc[orders.get("reason", pd.Series(dtype=object)) == "safety_deleveraging", "delta_weight"].sum()
        ) if not orders.empty else 0.0
        return orders, {
            "total_target_drift": total_drift,
            "normal_turnover_weight": normal_turnover,
            "planned_safety_sell_weight": planned_safety_sell_weight,
            "unresolved_safety_exposure": max(remaining_safety_shortfall, 0.0),
            "best_replacement_edge_10d": float(replacement_edge),
            "replacement_opportunity_sell_count": int(
                orders.get("reason", pd.Series(dtype=object)).astype(str).eq("replacement_opportunity_exit").sum()
            ) if not orders.empty else 0,
            "active_replacement_pair_count": int(len(replacement_pairs)),
            "same_symbol_action_conflict_count": int(len(action_conflicts)),
            "same_symbol_action_conflict_contract": "sell_precedence_v1",
            **action_plan_diagnostics,
            "profit_giveback_observation_count": _flag_count(eligible, "profit_giveback_exit"),
            "post_entry_failure_exit_count": int(
                orders.get("reason", pd.Series(dtype=object)).astype(str).eq("post_entry_failure_exit").sum()
            ) if not orders.empty else 0,
            "trend_break_observation_count": int(
                eligible.apply(_trend_break_exit, axis=1).sum()
            ) if eligible is not None and not eligible.empty else 0,
            "volume_distribution_observation_count": int(
                eligible.apply(_volume_distribution_exit, axis=1).sum()
            ) if eligible is not None and not eligible.empty else 0,
        }

    @staticmethod
    def _order_row(context, symbol, old, new, reason, candidate_row=None):
        delta = float(new) - float(old)
        get = candidate_row.get if candidate_row is not None else lambda key, default=None: default
        canonical_reason = canonical_exit_reason(reason)
        if (
            delta > 0
            and float(old) <= 1e-12
            and bool(context.catchup_allowed)
            and not bool(context.allow_normal_rebalance)
            and canonical_reason == "normal_buy"
        ):
            canonical_reason = "exposure_catchup_buy"
        add_decision_type = str(get("add_decision_type", "") or "")
        action_arbitration = arbitrate_position_actions(
            {
                "exit": bool(
                    delta < 0
                    and canonical_reason
                    not in {"normal_sell", "replacement_opportunity_exit"}
                ),
                "active_replacement": canonical_reason
                in {"replacement_opportunity_exit", "replacement_opportunity_buy"},
                "loser_averaging": bool(
                    delta > 0
                    and float(old) > 1e-12
                    and add_decision_type == "loser_averaging"
                ),
                "winner_pyramiding": bool(
                    delta > 0
                    and float(old) > 1e-12
                    and add_decision_type == "winner_pyramiding"
                ),
                "new_entry": bool(delta > 0 and float(old) <= 1e-12),
                "normal_rebalance": bool(
                    canonical_reason in {"normal_buy", "normal_sell"}
                    and not (
                        delta > 0
                        and float(old) > 1e-12
                        and add_decision_type
                    )
                ),
            }
        )
        return {
            "decision_id": context.decision_id,
            "decision_date": pd.Timestamp(context.decision_date),
            "execution_date": pd.Timestamp(context.decision_date) + pd.offsets.BDay(1),
            "symbol": symbol,
            "side": "buy" if delta > 0 else "sell",
            "action_plan_id": f"{context.decision_id}|action_plan",
            "action_proposal_id": (
                f"{context.decision_id}|{symbol}|"
                f"{'buy' if delta > 0 else 'sell'}|{canonical_reason}"
            ),
            "action_plan_selected": True,
            "action_plan_contract": "scap_v2_unique_action_plan_v1",
            "scap_candidate_utility": get("scap_candidate_utility", pd.NA),
            "add_expected_net_profit_lcb": get(
                "add_expected_net_profit_lcb", pd.NA
            ),
            "current_weight": float(old),
            "target_weight": float(new),
            "delta_weight": delta,
            "reason": canonical_reason,
            "priority": ORDER_PRIORITIES[canonical_reason],
            "pending_policy": "daily_expiry" if delta > 0 else "persistent_sell_intent",
            "liquidation_intent": bool(
                delta < 0
                and (
                    is_full_liquidation_reason(reason)
                    or float(new) <= 1e-12
                )
            ),
            "position_state": get("position_state", ""),
            "position_exit_reason": get("position_exit_reason", ""),
            "add_layer": get("add_layer", pd.NA),
            "add_allowed": bool(get("add_allowed", False)),
            "add_block_reason": get("add_block_reason", ""),
            "add_decision_type": add_decision_type,
            "unified_action_selected": action_arbitration.selected_action,
            "unified_action_proposals": "|".join(
                action_arbitration.proposed_actions
            ),
            "unified_action_vetoed": "|".join(
                action_arbitration.vetoed_actions
            ),
            "unified_action_conflict_count": action_arbitration.conflict_count,
            "unified_action_contract": action_arbitration.contract,
            "entry_matrix_score": get("entry_matrix_score", pd.NA),
            "entry_alpha_score": get("entry_alpha_score", pd.NA),
            "entry_timing_score": get("entry_timing_score", pd.NA),
            "entry_liquidity_score": get("entry_liquidity_score", pd.NA),
            "alpha_quality_score": get("alpha_quality_score", pd.NA),
            "surge_capture_score": get("surge_capture_score", pd.NA),
            "follow_through_score": get("follow_through_score", pd.NA),
            "exhaustion_score": get("exhaustion_score", pd.NA),
            "entry_success_probability": get("entry_success_probability", pd.NA),
            "entry_size_tier": get("entry_size_tier", ""),
            "planned_entry_lots": get("planned_entry_lots", pd.NA),
            "empirical_distribution_score": get("empirical_distribution_score", pd.NA),
            "final_entry_score": get("final_entry_score", pd.NA),
            "tail_risk_proxy": get("tail_risk_proxy", pd.NA),
            "trend_direction_score": get("trend_direction_score", pd.NA),
            "peak_decay_score": get("peak_decay_score", pd.NA),
            "profit_protection_pressure": get("profit_protection_pressure", pd.NA),
            "dynamic_giveback_limit": get("dynamic_giveback_limit", pd.NA),
            "future_loss_risk_score": get("future_loss_risk_score", pd.NA),
            "downtrend_decay_score": get("downtrend_decay_score", pd.NA),
            "post_entry_failure_score": get("post_entry_failure_score", pd.NA),
            "orderflow_candidate_score": get("orderflow_candidate_score", pd.NA),
            "reversal_entry_score": get("reversal_entry_score", pd.NA),
            "breakout_gate_score": get("breakout_gate_score", pd.NA),
            "trend_hold_score": get("trend_hold_score", pd.NA),
            "alpha_active_model_count": get("alpha_active_model_count", pd.NA),
            "alpha_active_module_count": get("alpha_active_module_count", pd.NA),
            "alpha_active_family_count": get("alpha_active_family_count", pd.NA),
            "alpha_max_active_module_share": get("alpha_max_active_module_share", pd.NA),
            "alpha_range_grid_vote_share": get("alpha_range_grid_vote_share", pd.NA),
            "entry_alpha_vote_count": get("entry_alpha_vote_count", pd.NA),
            "timing_filter_vote_count": get("timing_filter_vote_count", pd.NA),
            "risk_override_vote_count": get("risk_override_vote_count", pd.NA),
            "liquidity_guard_vote_count": get("liquidity_guard_vote_count", pd.NA),
            "hold_validation_vote_count": get("hold_validation_vote_count", pd.NA),
            "sell_trigger_vote_count": get("sell_trigger_vote_count", pd.NA),
            "state_machine_role_pass": bool(get("state_machine_role_pass", False)),
            "state_machine_role_block_reason": get("state_machine_role_block_reason", ""),
            "strategy_logic_version": get("strategy_logic_version", ""),
            "cabinet_native_final_score": get("cabinet_native_final_score", pd.NA),
            "mainline_v3_score_authority": get("mainline_v3_score_authority", ""),
            "mainline_v3_score_authority_version": get(
                "mainline_v3_score_authority_version", ""
            ),
            "mainline_v3_selection_evaluated": bool(
                get("mainline_v3_selection_evaluated", False)
            ),
            "v31_reliability_score": get("v31_reliability_score", pd.NA),
            "v31_reliability_score_coverage": get("v31_reliability_score_coverage", pd.NA),
            "v31_reliability_contract": get("v31_reliability_contract", pd.NA),
            "v31_calibration_window": get("v31_calibration_window", pd.NA),
            "v31_score_formula": get("v31_score_formula", pd.NA),
            "v31_score_authority": get("v31_score_authority", pd.NA),
            "v31_strict_entry_paper_only": get("v31_strict_entry_paper_only", pd.NA),
            "monthly_lgbm_raw_score": get("monthly_lgbm_raw_score", pd.NA),
            "monthly_lgbm_rank_percentile": get("monthly_lgbm_rank_percentile", pd.NA),
            "monthly_lgbm_model_month": get("monthly_lgbm_model_month", ""),
            "monthly_lgbm_trained_as_of": get("monthly_lgbm_trained_as_of", pd.NaT),
            "monthly_lgbm_runtime_model": get("monthly_lgbm_runtime_model", ""),
            "hybrid_rule_rank_percentile": get("hybrid_rule_rank_percentile", pd.NA),
            "hybrid_ml_rank_percentile": get("hybrid_ml_rank_percentile", pd.NA),
            "hybrid_ml_weight": get("hybrid_ml_weight", pd.NA),
            "hybrid_rule_weight": get("hybrid_rule_weight", pd.NA),
            "hybrid_final_score": get("hybrid_final_score", pd.NA),
            "hybrid_fusion_status": get("hybrid_fusion_status", ""),
            "hybrid_fusion_formula_version": get("hybrid_fusion_formula_version", ""),
            "hybrid_score_authority": get("hybrid_score_authority", ""),
            "cabinet_base_entry_score": get("cabinet_base_entry_score", pd.NA),
            "cabinet_strict_entry_score": get("cabinet_strict_entry_score", pd.NA),
            "cabinet_proxy_entry_score": get("cabinet_proxy_entry_score", pd.NA),
            "cabinet_timing_score": get("cabinet_timing_score", pd.NA),
            "cabinet_liquidity_health_score": get("cabinet_liquidity_health_score", pd.NA),
            "cabinet_risk_safety_score": get("cabinet_risk_safety_score", pd.NA),
            "cabinet_hold_support_score": get("cabinet_hold_support_score", pd.NA),
            "cabinet_entry_thesis": get("cabinet_entry_thesis", ""),
            "cabinet_entry_thesis_support": get("cabinet_entry_thesis_support", pd.NA),
            "mainline_v3_one_lot_cash_required": get("mainline_v3_one_lot_cash_required", pd.NA),
            "mainline_v3_one_lot_weight": get("mainline_v3_one_lot_weight", pd.NA),
            "mainline_v3_lot_feasible": get("mainline_v3_lot_feasible", pd.NA),
            "comparable_value_horizon_days": get("comparable_value_horizon_days", pd.NA),
            "comparable_expected_alpha": get("comparable_expected_alpha", pd.NA),
            "comparable_alpha_lcb": get("comparable_alpha_lcb", pd.NA),
            "comparable_value_contract": get("comparable_value_contract", ""),
            "replacement_pair_id": "",
            "replacement_paired_symbol": "",
            "replacement_pair_leg": "",
            "replacement_horizon_days": pd.NA,
            "replacement_expected_net_edge": pd.NA,
            "replacement_lcb_net_edge": pd.NA,
            "replacement_cost_rate": pd.NA,
            "replacement_contract": "",
        }


def _prepare_candidates(candidates):
    data = candidates.copy()
    required = {"symbol", "alpha_score", "alpha_percentile", "volatility_20"}
    missing = sorted(required - set(data.columns))
    if missing:
        raise ValueError(f"President candidates missing columns: {missing}")
    data["alpha_collapse_exit"] = data.get("alpha_collapse_exit", False)
    data["expected_return_5d"] = data.get("expected_return_5d", pd.NA)
    data["aggregate_confidence"] = data.get("aggregate_confidence", pd.NA)
    data["primary_score"] = data.get("primary_score", data["alpha_score"])
    data["score_authority"] = data.get("score_authority", "exploratory_alpha_fallback")
    if "candidate_rank" not in data.columns:
        ordered = data.sort_values(["primary_score", "symbol"], ascending=[False, True]).index
        data.loc[ordered, "candidate_rank"] = range(1, len(data) + 1)
    return data


def _state_machine_role_gate_pass(candidate_row) -> bool:
    if candidate_row is None:
        return False
    if "state_machine_role_pass" not in candidate_row:
        return True
    value = candidate_row.get("state_machine_role_pass", False)
    if pd.isna(value):
        return False
    return bool(value)


def _apply_policy_risk_hard_gate(allocated: pd.DataFrame, *, current_weights, diagnostics: dict) -> tuple[pd.DataFrame, dict]:
    data = allocated.copy()
    if data.empty:
        return data, {
            "risk_hard_gate_enabled": True,
            "risk_new_buy_block_applied": False,
            "risk_catchup_block_applied": False,
        }
    held = {str(symbol) for symbol, weight in dict(current_weights or {}).items() if float(weight) > 1e-12}
    new_buy_block = bool(diagnostics.get("risk_new_buy_block", False))
    catchup_block = bool(diagnostics.get("risk_catchup_block", False))
    blocked_new_weight = 0.0
    if new_buy_block and "symbol" in data.columns:
        is_new = ~data["symbol"].astype(str).isin(held)
        blocked_new_weight = float(pd.to_numeric(data.loc[is_new, "target_weight"], errors="coerce").fillna(0.0).sum())
        data.loc[is_new, "target_weight"] = 0.0
    return data, {
        "risk_hard_gate_enabled": True,
        "risk_new_buy_block_applied": bool(new_buy_block),
        "risk_catchup_block_applied": bool(catchup_block),
        "risk_blocked_new_buy_weight": blocked_new_weight,
    }


def _order_reason(symbol, delta, candidate_row, context, replacement_edge: float = 0.0, exit_mode: str = "full"):
    if delta < 0 and symbol in context.hard_qualification_symbols:
        return "qualification_exit"
    if delta < 0 and candidate_row is not None and bool(candidate_row.get("exit_state", False)):
        exit_reason = canonical_exit_reason(
            candidate_row.get("position_exit_reason", "")
        )
        if exit_reason in ORDER_PRIORITIES:
            return exit_reason
        return "normal_sell"
    if delta < 0 and candidate_row is not None and bool(candidate_row.get("stale_time_reduce", False)):
        return "stale_time_reduce"
    if delta < 0 and candidate_row is not None and bool(candidate_row.get("alpha_collapse_exit", False)):
        return "alpha_collapse_consensus"
    mode = str(exit_mode or "observe_complex_exit").lower()
    if delta < 0 and candidate_row is not None and bool(candidate_row.get("post_entry_failure_exit", False)):
        return "post_entry_failure_exit"
    if delta < 0 and mode in {"simple", "minimal", "no_complex_exit", "observe_complex_exit", "full"}:
        return "normal_sell"
    if delta < 0 and candidate_row is not None:
        if mode in {"active_complex_exit", "complex_exit"}:
            if bool(candidate_row.get("profit_giveback_exit", False)):
                return "profit_giveback_exit"
            if _volume_distribution_exit(candidate_row):
                return "volume_distribution_exit"
            if _trend_break_exit(candidate_row):
                return "trend_break_exit"
            if _replacement_opportunity_exit(candidate_row, replacement_edge):
                return "replacement_opportunity_exit"
    if delta > 0 and candidate_row is not None and float(
        context.current_weights.get(symbol, 0.0)
    ) > 1e-12:
        add_type = str(candidate_row.get("add_decision_type", "") or "")
        if add_type == "loser_averaging":
            return "loser_averaging_buy"
        if add_type == "winner_pyramiding":
            return "winner_pyramiding_buy"
    return "normal_buy" if delta > 0 else "normal_sell"


def _best_replacement_edge(eligible: pd.DataFrame, held_symbols: set[str]) -> float:
    if eligible is None or eligible.empty or "symbol" not in eligible.columns:
        return 0.0
    data = eligible[~eligible["symbol"].astype(str).isin(held_symbols)].copy()
    if data.empty:
        return 0.0
    # This diagnostic is formatted as a return in reports, so ordinal ranking
    # scores are never an admissible fallback.
    score_col = "conservative_expected_edge_10d" if "conservative_expected_edge_10d" in data.columns else "expected_edge_10d"
    score_source = data[score_col] if score_col in data.columns else pd.Series(float("nan"), index=data.index)
    score = pd.to_numeric(score_source, errors="coerce").dropna()
    if score.empty:
        return 0.0
    return float(score.quantile(0.90))


def _replacement_opportunity_exit(candidate_row, replacement_edge: float) -> bool:
    hold_edge = _hold_edge_after_lifecycle_penalty(candidate_row)
    alpha_percentile = pd.to_numeric(
        pd.Series([candidate_row.get("alpha_percentile", 0.5)]),
        errors="coerce",
    ).fillna(0.5).iloc[0]
    edge_gap = float(replacement_edge) - float(hold_edge)
    giveback = _safe_row_float(candidate_row, "position_giveback_from_peak", 0.0)
    mfe = _safe_row_float(candidate_row, "position_mfe", 0.0)
    return bool(
        (edge_gap >= 0.12 and alpha_percentile < 0.55)
        or (edge_gap >= 0.08 and mfe >= 0.06 and giveback >= 0.35)
    )


def _hold_edge_after_lifecycle_penalty(candidate_row) -> float:
    edge = _safe_row_float(candidate_row, "conservative_expected_edge_10d", None)
    if edge is None:
        edge = _safe_row_float(candidate_row, "expected_edge_10d", 0.0)
    giveback = _safe_row_float(candidate_row, "position_giveback_from_peak", 0.0)
    mfe = _safe_row_float(candidate_row, "position_mfe", 0.0)
    mae = abs(_safe_row_float(candidate_row, "position_mae", 0.0))
    unrealized = _safe_row_float(candidate_row, "position_unrealized_return", 0.0)
    lifecycle_penalty = 0.0
    if mfe >= 0.06:
        lifecycle_penalty += max(giveback - 0.25, 0.0) * 0.006
    if mae >= 0.05 and unrealized <= 0.0:
        lifecycle_penalty += 0.003
    if bool(candidate_row.get("post_entry_failure_exit", False)):
        lifecycle_penalty += 0.006
    return float(edge) - float(lifecycle_penalty)


def _holding_age_review_passed(candidate_row) -> bool:
    if candidate_row is None:
        return False
    if bool(candidate_row.get("alpha_collapse_exit", False)):
        return False
    if bool(candidate_row.get("post_entry_failure_exit", False)):
        return False
    alpha_percentile = float(pd.to_numeric(pd.Series([candidate_row.get("alpha_percentile", 0.0)]), errors="coerce").fillna(0.0).iloc[0])
    expected_return = float(pd.to_numeric(pd.Series([candidate_row.get("expected_return_5d", 0.0)]), errors="coerce").fillna(0.0).iloc[0])
    trend_hold_score = float(pd.to_numeric(pd.Series([candidate_row.get("trend_hold_score", 0.5)]), errors="coerce").fillna(0.5).iloc[0])
    if trend_hold_score < 0.35 and alpha_percentile < 0.45 and expected_return < 0.0:
        return False
    return alpha_percentile >= 0.50 or expected_return >= 0.0


def _apply_unique_action_plan(
    orders: pd.DataFrame,
    *,
    context: DecisionContext,
    candidates: pd.DataFrame,
    safety_cap: float,
) -> tuple[pd.DataFrame, dict]:
    """Make one ActionPlan the final SCAP strategy authority for all orders."""
    if orders is None or orders.empty:
        return orders, {}
    candidate_index = candidates.set_index("symbol", drop=False)
    proposals: list[ActionProposal] = []
    proposal_by_row: dict[int, ActionProposal] = {}
    hard_exit_reasons = {
        "safety_deleveraging",
        "qualification_exit",
        "hard_stop_exit",
        "profit_hard_stop_exit",
        "loss_containment_exit",
        "alpha_collapse_consensus",
        "profit_giveback_exit",
        "post_entry_failure_exit",
        "signal_failure_exit",
        "thesis_failure_exit",
        "stale_time_exit",
        "stale_time_reduce",
    }
    for index, order in orders.iterrows():
        symbol = str(order.get("symbol", ""))
        row = candidate_index.loc[symbol] if symbol in candidate_index.index else None
        reason = str(order.get("reason", ""))
        side = str(order.get("side", "")).lower()
        pair_id = str(order.get("replacement_pair_id", "") or "")
        old_weight = _safe_row_float(order, "current_weight", 0.0)
        delta_weight = abs(_safe_row_float(order, "delta_weight", 0.0))
        if reason == "safety_deleveraging":
            action_type = "safety_exit"
        elif reason in hard_exit_reasons:
            action_type = "hard_exit"
        elif reason == "replacement_opportunity_exit":
            action_type = "replacement_sell"
        elif reason == "replacement_opportunity_buy":
            action_type = "replacement_buy"
        elif side == "buy" and old_weight > 1e-12:
            add_type = str(
                row.get("add_decision_type", "add") if row is not None else "add"
            )
            action_type = add_type if add_type else "add"
        elif side == "buy":
            action_type = "new_entry"
        else:
            action_type = "hard_exit"
        if action_type in {"safety_exit", "hard_exit"}:
            robust = 0.0
        elif action_type in {"replacement_sell", "replacement_buy"}:
            robust = max(
                _safe_row_float(order, "replacement_lcb_net_edge", 0.0)
                * float(context.nav_amount)
                * max(delta_weight, 1e-6)
                / 2.0,
                0.0,
            )
        elif action_type in {"loser_averaging", "winner_pyramiding", "add"}:
            robust = _safe_row_float(
                row, "add_expected_net_profit_lcb", 0.0
            ) if row is not None else 0.0
        else:
            robust = _safe_row_float(
                row, "scap_candidate_utility", 0.0
            ) if row is not None else 0.0
        exact_cost = (
            _safe_row_float(row, "scap_estimated_total_cost_amount", 0.0)
            if row is not None
            else 0.0
        )
        proposal = ActionProposal(
            proposal_id=str(order.get("action_proposal_id")),
            decision_id=str(context.decision_id),
            symbol=symbol,
            action_type=action_type,
            source_module=str(order.get("unified_action_selected", action_type)),
            requested_lots=1,
            baseline_action=(
                "hold_cash" if action_type == "new_entry" else "hold_position"
            ),
            horizon_sessions=max(
                int(_safe_row_float(row, "comparable_value_horizon_days", 10.0))
                if row is not None
                else 10,
                1,
            ),
            expected_net_profit_amount=float(robust),
            robust_net_profit_amount=float(robust),
            downside_cvar_amount=(
                float(context.nav_amount) * delta_weight * 0.30
                if side == "buy"
                else 0.0
            ),
            exact_cost_amount=max(float(exact_cost), 0.0),
            funding_cash_amount=(
                float(context.nav_amount) * delta_weight
                if side == "buy"
                else 0.0
            ),
            replacement_pair_id=pair_id,
        )
        proposals.append(proposal)
        proposal_by_row[int(index)] = proposal
    authorization = ExposureAuthorization(
        decision_id=str(context.decision_id),
        nav_amount=max(float(context.nav_amount), 1e-12),
        # Target weights have already consumed the policy exposure cap. This
        # final authority checks the complete order set against the same cap
        # in CNY while allowing paired sells to remain atomic.
        risk_exposure_ceiling=min(max(float(safety_cap), 0.0), 1.0),
        cash_buffer_amount=max(float(context.cash_buffer_amount), 0.0),
        per_name_structural_cap=min(
            max(float(context.per_name_structural_cap), 0.0), 1.0
        ),
        per_name_stress_budget_amount=max(
            float(context.nav_amount) * float(context.per_name_structural_cap) * 0.40,
            0.0,
        ),
        portfolio_stress_budget_amount=max(
            float(context.portfolio_stress_budget_amount), 0.0
        ),
        new_entry_allowed=True,
        add_allowed=True,
        replacement_allowed=True,
        covariance_state=(
            "available"
            if context.covariance_matrix is not None
            and not context.covariance_matrix.empty
            else "fallback"
        ),
        fallback_risk_model="preauthorized_target_plus_one_lot_stress",
    )
    # The provisional target already enforces the cap; use zero base exposure
    # here so funding is not double-counted. Runtime integrity still compares
    # actual exposure with the original authorization on the following day.
    thesis_by_symbol = dict(
        zip(
            candidates["symbol"].astype(str),
            candidates.get(
                "cabinet_entry_thesis", pd.Series("", index=candidates.index)
            )
            .fillna("")
            .astype(str),
        )
    )
    plan = optimize_action_proposals(
        proposals,
        authorization=authorization,
        current_lots_by_symbol={
            str(symbol): 1
            for symbol, weight in context.current_weights.items()
            if float(weight) > 1e-12
        },
        current_exposure=0.0,
        max_positions=max(int(context.top_n), 1),
        thesis_by_symbol=thesis_by_symbol,
        max_names_per_thesis=2,
        correlation_matrix=context.covariance_matrix,
    )
    selected = set(plan.selected_proposal_ids)
    keep = [
        index
        for index, proposal in proposal_by_row.items()
        if proposal.proposal_id in selected
    ]
    result = orders.loc[keep].copy().reset_index(drop=True)
    result["action_plan_id"] = f"{context.decision_id}|action_plan"
    result["action_plan_selected"] = True
    result["action_plan_contract"] = plan.contract_version
    return result, {
        "action_plan_id": f"{context.decision_id}|action_plan",
        "action_plan_contract": plan.contract_version,
        "action_plan_solver_status": plan.solver_status,
        "action_plan_selected_count": int(len(plan.selected_proposal_ids)),
        "action_plan_rejected_count": int(len(plan.rejected_proposals)),
        "action_plan_expected_net_profit_amount": float(
            plan.expected_net_profit_amount
        ),
        "action_plan_robust_net_profit_amount": float(plan.robust_net_profit_amount),
        "action_plan_downside_cvar_amount": float(plan.downside_cvar_amount),
        "action_plan_projected_exposure": float(plan.projected_exposure),
    }


def _select_scap_discrete_entries(
    candidates: pd.DataFrame,
    *,
    incremental_exposure_cap: float,
    correlation_matrix: pd.DataFrame | None = None,
) -> set[str]:
    """Use the unique SCAP-V2 integer optimizer for final entry authority."""
    if candidates is None or candidates.empty or float(incremental_exposure_cap) <= 0.0:
        return set()
    data = candidates.copy()
    data["_lot_weight"] = pd.to_numeric(
        data.get("mainline_v3_one_lot_weight"),
        errors="coerce",
    )
    data["_utility"] = pd.to_numeric(
        data.get("scap_candidate_utility"),
        errors="coerce",
    )
    data = data[
        data["_lot_weight"].notna()
        & data["_lot_weight"].gt(0.0)
        & data["_utility"].notna()
        & data["_utility"].gt(0.0)
    ].copy()
    if data.empty:
        return set()
    decision_id = str(
        data.get("decision_id", pd.Series("scap_entry_plan", index=data.index))
        .fillna("scap_entry_plan")
        .astype(str)
        .iloc[0]
    )
    proposals = []
    for index, row in data.iterrows():
        symbol = str(row["symbol"])
        lot_weight = float(row["_lot_weight"])
        utility = float(row["_utility"])
        proposals.append(
            ActionProposal(
                proposal_id=f"{decision_id}|new_entry|{symbol}|{index}",
                decision_id=decision_id,
                symbol=symbol,
                action_type="new_entry",
                source_module="mainline_v3",
                requested_lots=1,
                baseline_action="hold_cash",
                horizon_sessions=int(
                    pd.to_numeric(
                        pd.Series([row.get("comparable_value_horizon_days", 10)]),
                        errors="coerce",
                    ).fillna(10).iloc[0]
                ),
                expected_net_profit_amount=utility,
                robust_net_profit_amount=utility,
                downside_cvar_amount=max(lot_weight * 0.30, 0.0),
                exact_cost_amount=max(
                    float(
                        pd.to_numeric(
                            pd.Series([row.get("scap_estimated_total_cost_amount", 0.0)]),
                            errors="coerce",
                        ).fillna(0.0).iloc[0]
                    ),
                    0.0,
                ),
                funding_cash_amount=lot_weight,
            )
        )
    authorization = ExposureAuthorization(
        decision_id=decision_id,
        nav_amount=1.0,
        risk_exposure_ceiling=min(max(float(incremental_exposure_cap), 0.0), 1.0),
        cash_buffer_amount=0.0,
        per_name_structural_cap=1.0,
        per_name_stress_budget_amount=1.0,
        portfolio_stress_budget_amount=1.0,
        new_entry_allowed=True,
        add_allowed=True,
        replacement_allowed=True,
        covariance_state="policy_supplied",
        fallback_risk_model="one_lot_weight_stress",
    )
    plan = optimize_action_proposals(
        proposals,
        authorization=authorization,
        max_positions=len(data),
        thesis_by_symbol=dict(
            zip(
                data["symbol"].astype(str),
                data.get(
                    "cabinet_entry_thesis",
                    pd.Series("", index=data.index),
                ).fillna("").astype(str),
            )
        ),
        max_names_per_thesis=2,
        correlation_matrix=correlation_matrix,
    )
    selected_ids = set(plan.selected_proposal_ids)
    return {
        proposal.symbol
        for proposal in proposals
        if proposal.proposal_id in selected_ids
    }


def _trend_break_exit(candidate_row) -> bool:
    close_to_ma20 = pd.to_numeric(pd.Series([candidate_row.get("close_to_ma20", 0.0)]), errors="coerce").fillna(0.0).iloc[0]
    ret_20 = pd.to_numeric(pd.Series([candidate_row.get("ret_20", 0.0)]), errors="coerce").fillna(0.0).iloc[0]
    alpha_percentile = pd.to_numeric(pd.Series([candidate_row.get("alpha_percentile", 0.5)]), errors="coerce").fillna(0.5).iloc[0]
    return bool(close_to_ma20 < -0.08 and ret_20 < -0.08 and alpha_percentile < 0.45)


def _volume_distribution_exit(candidate_row) -> bool:
    amount = pd.to_numeric(pd.Series([candidate_row.get("amount", 0.0)]), errors="coerce").fillna(0.0).iloc[0]
    amount_ma20 = pd.to_numeric(pd.Series([candidate_row.get("amount_ma20", 0.0)]), errors="coerce").fillna(0.0).iloc[0]
    close_to_ma20 = pd.to_numeric(pd.Series([candidate_row.get("close_to_ma20", 0.0)]), errors="coerce").fillna(0.0).iloc[0]
    ret_20 = pd.to_numeric(pd.Series([candidate_row.get("ret_20", 0.0)]), errors="coerce").fillna(0.0).iloc[0]
    return bool(amount_ma20 > 0 and amount > amount_ma20 * 1.8 and close_to_ma20 < -0.03 and ret_20 < 0.0)


def _safe_row_float(candidate_row, column: str, default):
    value = pd.to_numeric(pd.Series([candidate_row.get(column, default)]), errors="coerce").dropna()
    if value.empty:
        return default
    return float(value.iloc[0])


def _flag_count(data: pd.DataFrame, column: str) -> int:
    if data is None or data.empty or column not in data.columns:
        return 0
    return int(data[column].fillna(False).astype(bool).sum())
