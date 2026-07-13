"""Deterministic phase-one president policy."""
from __future__ import annotations

import pandas as pd

from config import GOVERNANCE_SINGLE_WEIGHT_DRIFT, GOVERNANCE_TOTAL_WEIGHT_DRIFT
from functions.decision_council.allocation import PortfolioConstructionCommittee
from functions.decision_council.contracts import DecisionContext


ORDER_PRIORITIES = {
    "safety_deleveraging": 0,
    "qualification_exit": 1,
    "hard_stop_exit": 1,
    "alpha_collapse_consensus": 2,
    "trend_break_exit": 3,
    "profit_giveback_exit": 3,
    "post_entry_failure_exit": 3,
    "signal_failure_exit": 3,
    "stale_time_exit": 3,
    "stale_time_reduce": 4,
    "volume_distribution_exit": 4,
    "replacement_opportunity_exit": 4,
    "single_name_risk_trim": 5,
    "normal_sell": 4,
    "normal_buy": 5,
    "force_deploy_diversify_buy": 5,
    "force_deploy_defensive_buy": 6,
}
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
    "position_state",
    "position_exit_reason",
    "add_layer",
    "add_allowed",
    "add_block_reason",
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
    "state_machine_role_pass",
    "state_machine_role_block_reason",
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
        selected_symbols = list(dict.fromkeys(held_symbols))
        for symbol in ranked_symbols:
            if symbol not in selected_symbols and len(selected_symbols) < int(context.top_n):
                selected_symbols.append(symbol)
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
        target_weights = dict(zip(allocated["symbol"], allocated["target_weight"]))
        target_weights.update(locked_weights)
        ideal = self._ideal_plan(context, allocated, locked_weights, allocation_diagnostics)
        replacement_edge = _best_replacement_edge(eligible, set(context.current_weights))
        orders, order_diagnostics = self._build_orders(
            context,
            target_weights,
            eligible,
            safety_cap,
            replacement_edge,
            risk_catchup_block=bool(allocation_diagnostics.get("risk_catchup_block_applied", False)),
        )
        diagnostics = {
            **allocation_diagnostics,
            **order_diagnostics,
            "locked_nominal_weight": sum(locked_weights.values()),
            "preserved_unranked_nominal_weight": 0.0,
            "target_exposure": sum(target_weights.values()),
            "sector_cap_enabled": self.enable_sector_cap,
            "safety_agent_enabled": self.enable_safety_agent,
        }
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

    def _build_orders(self, context, target_weights, eligible, safety_cap, replacement_edge: float, *, risk_catchup_block: bool = False):
        current = {str(symbol): float(weight) for symbol, weight in context.current_weights.items()}
        symbols = sorted(set(current) | set(target_weights))
        safety_shortfall = max(sum(current.values()) - float(safety_cap), 0.0)
        rows = []
        sell_symbols = set()
        normal_turnover = 0.0
        total_drift = sum(abs(target_weights.get(symbol, 0.0) - current.get(symbol, 0.0)) for symbol in symbols)
        candidate_index = eligible.set_index("symbol", drop=False)
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
            sell_weight = min(float(old), remaining_safety_shortfall)
            row = candidate_index.loc[symbol] if symbol in candidate_index.index else None
            rows.append(self._order_row(context, symbol, old, old - sell_weight, "safety_deleveraging", row))
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
                and str(row.get("position_state", "")).strip().lower() in {"building", "strong_building", "holding", "watching"}
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
                "alpha_collapse_consensus",
                "profit_giveback_exit",
                "post_entry_failure_exit",
                "signal_failure_exit",
                "stale_time_exit",
                "stale_time_reduce",
            }
            if not is_forced_sell:
                if not context.allow_normal_rebalance and not is_catchup_buy and not is_confirmed_entry_buy:
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
                if abs(delta) < GOVERNANCE_SINGLE_WEIGHT_DRIFT and total_drift < GOVERNANCE_TOTAL_WEIGHT_DRIFT:
                    continue
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
        return {
            "decision_id": context.decision_id,
            "decision_date": pd.Timestamp(context.decision_date),
            "execution_date": pd.Timestamp(context.decision_date) + pd.offsets.BDay(1),
            "symbol": symbol,
            "side": "buy" if delta > 0 else "sell",
            "current_weight": float(old),
            "target_weight": float(new),
            "delta_weight": delta,
            "reason": reason,
            "priority": ORDER_PRIORITIES[reason],
            "pending_policy": "daily_expiry" if delta > 0 else "persistent_sell_intent",
            "position_state": get("position_state", ""),
            "position_exit_reason": get("position_exit_reason", ""),
            "add_layer": get("add_layer", pd.NA),
            "add_allowed": bool(get("add_allowed", False)),
            "add_block_reason": get("add_block_reason", ""),
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
        exit_reason = str(candidate_row.get("position_exit_reason", "") or "").strip()
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
    return "normal_buy" if delta > 0 else "normal_sell"


def _best_replacement_edge(eligible: pd.DataFrame, held_symbols: set[str]) -> float:
    if eligible is None or eligible.empty or "symbol" not in eligible.columns:
        return 0.0
    data = eligible[~eligible["symbol"].astype(str).isin(held_symbols)].copy()
    if data.empty:
        return 0.0
    score_col = "entry_matrix_score" if "entry_matrix_score" in data.columns else "expected_edge_10d"
    score_source = data[score_col] if score_col in data.columns else pd.Series(0.0, index=data.index)
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
    edge = _safe_row_float(candidate_row, "entry_matrix_score", None)
    if edge is None:
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
