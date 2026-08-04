"""Retail order sizing and diagnostics for governance backtests."""
from __future__ import annotations

import pandas as pd

from config import *  # noqa: F403 - retail rules are config-driven.
from functions.execution.cost_model import cost_kwargs_from_profile, estimate_trade_costs
from functions.execution.security_trading_rules import legal_buy_quantity, trading_rule_for
from functions.decision_council.mainline_v2 import is_mainline_v3_version


def _safe_float(value, default=0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def sort_retail_orders(runner, orders: pd.DataFrame) -> pd.DataFrame:
    if orders is None or orders.empty:
        return orders
    data = orders.copy()
    side = data.get("side", pd.Series("", index=data.index)).astype(str).str.lower()
    data["_retail_side_priority"] = side.map({"sell": 0, "buy": 1}).fillna(2)
    matrix = pd.to_numeric(data.get("entry_matrix_score", pd.Series(0.0, index=data.index)), errors="coerce").fillna(0.0)
    timing = pd.to_numeric(data.get("entry_timing_score", pd.Series(0.0, index=data.index)), errors="coerce").fillna(0.0)
    liquidity = pd.to_numeric(data.get("entry_liquidity_score", pd.Series(0.0, index=data.index)), errors="coerce").fillna(0.0)
    alpha = pd.to_numeric(data.get("entry_alpha_score", pd.Series(0.0, index=data.index)), errors="coerce").fillna(0.0)
    data["_retail_order_score"] = 0.50 * matrix + 0.25 * timing + 0.15 * liquidity + 0.10 * alpha
    sorted_data = data.sort_values(
        ["_retail_side_priority", "_retail_order_score", "priority", "symbol"],
        ascending=[True, False, True, True],
    )
    return sorted_data.drop(columns=["_retail_side_priority", "_retail_order_score"])

def adapt_retail_buy_order(
    runner,
    *,
    order,
    strategy_target_notional: float,
    order_price: float,
    nominal_nav: float,
    reserved_cash: float,
    initial_shares: float,
    one_lot_cash_required: float | None = None,
) -> tuple[float, str, str]:
    state = str(order.get("position_state", "") or "").strip().lower()
    action_plan_authorized = bool(order.get("action_plan_selected", False)) and bool(
        str(order.get("action_plan_id", "") or "").strip()
    )
    # SCAP-V3 Lean consumes factual cooldown/exit states before optimization.
    # The legacy ``blocked`` state is derived from the old entry-confirmation
    # score/tier and is not an execution fact.  Re-reading it here would turn
    # one authoritative ActionPlan into a second, hidden soft-score veto.
    if (
        not action_plan_authorized
        and (
            state in {"blocked", "cooldown", "exiting", "protecting_profit"}
            or bool(order.get("exit_state", False))
        )
    ):
        return 0.0, "blocked", "position_state"
    if order_price <= 0.0 or nominal_nav <= 0.0:
        return 0.0, "blocked", "invalid_price_or_nav"

    min_buffer = float(runner.capital_profile.get("min_cash_buffer", 0.0) or 0.0)
    single_cap = float(runner.capital_profile.get("retail_single_position_cap", 0.40) or 0.40)
    exposure_tolerance = float(runner.capital_profile.get("retail_target_exposure_tolerance", 0.10) or 0.10)
    strong_threshold = float(runner.capital_profile.get("retail_strong_entry_matrix_threshold", 0.75) or 0.75)
    entry_score = _safe_float(order.get("entry_matrix_score"), default=0.0)
    alpha_quality = _safe_float(order.get("alpha_quality_score"), default=0.0)
    follow_through = _safe_float(order.get("follow_through_score"), default=0.0)
    exhaustion = _safe_float(order.get("exhaustion_score"), default=0.0)
    downtrend = _safe_float(order.get("downtrend_decay_score"), default=0.0)
    entry_probability = _safe_float(order.get("entry_success_probability"), default=0.0)
    min_entry_score = float(runner.capital_profile.get("retail_min_entry_matrix_score", 0.0) or 0.0)
    tier = str(order.get("entry_size_tier", "") or "").strip().lower()
    rule = trading_rule_for(order.get("symbol"), trade_date=order.get("execution_date"))
    minimum_buy_quantity = float(rule.minimum_buy_quantity)
    force_deploy = runner.capital_usage_mode == GOVERNANCE_CAPITAL_USAGE_MODE_FORCE_DEPLOY
    cabinet_native = is_mainline_v3_version(getattr(runner, "strategy_logic_version", ""))
    if force_deploy and tier == "diversify_1_lot":
        min_entry_score = min(min_entry_score, float(GOVERNANCE_DIVERSIFY_ENTRY_MATRIX_MIN))
    elif tier == "starter_1_lot":
        min_entry_score = min(min_entry_score, float(GOVERNANCE_ENTRY_MATRIX_WATCH_THRESHOLD))
    one_lot_position_cap = float(
        runner.capital_profile.get("retail_one_lot_position_cap", single_cap) or single_cap
    )
    one_lot_cost = float(order_price) * minimum_buy_quantity
    one_lot_cash_required = (
        float(one_lot_cash_required)
        if one_lot_cash_required is not None
        else runner._retail_cash_required(side="buy", price=order_price, shares=minimum_buy_quantity)
    )
    available_cash = max(float(runner.cash) - float(reserved_cash), 0.0)
    affordable_cash = max(available_cash - min_buffer, 0.0)
    if one_lot_cash_required > affordable_cash:
        return 0.0, "blocked", "lot_size_cash_insufficient"

    current_weight = _safe_float(order.get("current_weight"), default=0.0)
    one_lot_weight = one_lot_cash_required / max(float(nominal_nav), 1e-12)
    if current_weight + one_lot_weight > single_cap + 1e-12:
        return 0.0, "blocked", "single_position_cap"
    if initial_shares < minimum_buy_quantity and one_lot_weight > one_lot_position_cap + 1e-12:
        return 0.0, "blocked", "one_lot_position_cap"

    target_exposure = 0.0
    if runner.exposure_rows:
        exposure_contract_row = runner.exposure_rows[-1]
        target_exposure = _safe_float(
            exposure_contract_row.get(
                "hard_exposure_ceiling"
                if action_plan_authorized
                else "target_exposure"
            ),
            default=0.0,
        )
        if action_plan_authorized:
            # The ActionPlan already optimized against the policy target.  The
            # execution adapter may re-check only the factual hard ceiling.
            exposure_tolerance = 0.0
    current_exposure = 0.0
    if runner.exposure_rows:
        current_exposure = _safe_float(runner.exposure_rows[-1].get("nominal_exposure"), default=0.0)
    if target_exposure > 1e-12 and current_exposure + one_lot_weight > target_exposure + exposure_tolerance + 1e-12:
        return 0.0, "blocked", "target_exposure_tolerance"

    if action_plan_authorized:
        # The unique ActionPlan already consumed every soft score, forecast,
        # and action conflict. Execution may still reject factual cash, lot,
        # position-state, or exposure violations, but cannot re-score or resize.
        if initial_shares < minimum_buy_quantity:
            return 0.0, "blocked", "action_plan_quantity_below_board_lot"
        full_cash_required = retail_cash_required(
            runner, side="buy", price=order_price, shares=initial_shares
        )
        if full_cash_required > affordable_cash + 1e-9:
            return 0.0, "blocked", "action_plan_cash_insufficient"
        full_weight = float(order_price) * float(initial_shares) / max(float(nominal_nav), 1e-12)
        if current_weight + full_weight > single_cap + 1e-12:
            return 0.0, "blocked", "action_plan_single_position_cap"
        if (
            target_exposure > 1e-12
            and current_exposure + full_weight
            > target_exposure + exposure_tolerance + 1e-12
        ):
            return 0.0, "blocked", "action_plan_target_exposure_tolerance"
        return initial_shares, "action_plan_unchanged", ""

    if initial_shares >= minimum_buy_quantity:
        return initial_shares, "unchanged", ""
    one_lot_tiers = {"basket_1_lot", "diversify_1_lot", "starter_1_lot", "starter_2_lot", "starter_strong"}
    if strategy_target_notional <= 0.0 and not (force_deploy and tier in one_lot_tiers) and tier != "basket_1_lot":
        return 0.0, "blocked", "target_notional_zero"
    if entry_score < min_entry_score:
        return 0.0, "blocked", "entry_matrix_score"
    if not cabinet_native and exhaustion >= float(GOVERNANCE_EXHAUSTION_BUY_MAX):
        return 0.0, "blocked", "exhaustion_block"
    if not cabinet_native and downtrend >= float(GOVERNANCE_DOWNTREND_DECAY_ADD_BLOCK):
        return 0.0, "blocked", "downtrend_decay_block"

    planned_lots = int(max(_safe_float(order.get("planned_entry_lots"), default=1.0), 1.0))
    if cabinet_native:
        planned_lots = 1
    elif tier == "starter_strong" or (
        entry_score >= max(strong_threshold, float(GOVERNANCE_ENTRY_MATRIX_STRONG_STARTER))
        and alpha_quality >= 0.70
        and follow_through >= float(GOVERNANCE_FOLLOW_THROUGH_STRONG)
    ):
        planned_lots = max(planned_lots, int(GOVERNANCE_RETAIL_STRONG_STARTER_LOTS))
    elif tier == "starter_2_lot" or (
        entry_score >= float(GOVERNANCE_ENTRY_MATRIX_STARTER_2)
        and follow_through >= float(GOVERNANCE_FOLLOW_THROUGH_STARTER_2)
    ):
        planned_lots = max(planned_lots, int(GOVERNANCE_RETAIL_STARTER_2_LOTS))
    else:
        planned_lots = 1

    max_cash_lots = int(affordable_cash // max(one_lot_cash_required, 1e-12))
    max_cap_lots = int(max((single_cap - current_weight) * max(float(nominal_nav), 1e-12), 0.0) // max(one_lot_cash_required, 1e-12))
    executable_lots = max(min(planned_lots, max_cash_lots, max_cap_lots), 0)
    if executable_lots <= 0:
        return 0.0, "blocked", "lot_size_cash_or_cap"
    requested = float(executable_lots) * minimum_buy_quantity
    shares = legal_buy_quantity(order.get("symbol"), requested, trade_date=order.get("execution_date"))
    if executable_lots >= 3:
        return shares, "upgraded_to_three_lots_strong", ""
    if executable_lots >= 2:
        return shares, "upgraded_to_two_lots", ""
    return shares, "upgraded_to_one_lot", ""

def retail_cash_required(runner, *, side: str, price: float, shares: float) -> float:
    if float(price) <= 0.0 or float(shares) <= 0.0:
        return 0.0
    costs = estimate_trade_costs(
        pd.DataFrame(
            [
                {
                    "side": str(side),
                    "price": float(price),
                    "target_shares": float(shares),
                }
            ]
        ),
        **cost_kwargs_from_profile(runner.capital_profile),
    )
    row = costs.iloc[0]
    return float(row.get("trade_notional", 0.0)) + float(row.get("total_cost", 0.0))

def record_retail_execution_diagnostic(
    runner,
    *,
    order,
    nominal_nav: float,
    price,
    one_lot_cost,
    strategy_target_notional: float,
    adjusted_target_notional: float,
    target_shares: float,
    available_cash: float,
    retail_action: str,
    retail_block_reason: str,
    one_lot_cash_required=None,
) -> None:
    # Zero-lot diagnostics are factual exchange-feasibility evidence and must
    # remain visible even when the optional retail buy adapter is disabled.
    if not runner._retail_lot_adapter_enabled and str(retail_action) != "blocked_zero_lot":
        return
    min_buffer = float(runner.capital_profile.get("min_cash_buffer", 0.0) or 0.0)
    adjusted_notional = _safe_float(adjusted_target_notional, default=0.0)
    single_after = _safe_float(order.get("current_weight"), default=0.0) + (
        adjusted_notional / max(float(nominal_nav), 1e-12)
    )
    runner.retail_execution_rows.append(
        {
            "decision_id": order.get("decision_id", ""),
            "execution_date": order.get("execution_date", pd.NaT),
            "symbol": str(order.get("symbol", "")),
            "side": str(order.get("side", "")),
            "strategy_target_weight": _safe_float(order.get("delta_weight"), default=0.0),
            "strategy_target_notional": float(strategy_target_notional),
            "adjusted_target_notional": adjusted_notional,
            "price": price,
            "one_lot_cost": one_lot_cost,
            "one_lot_cash_required": _safe_float(one_lot_cash_required, default=_safe_float(one_lot_cost, default=0.0)),
            "target_shares": float(target_shares or 0.0),
            "available_cash": float(available_cash),
            "cash_buffer_required": min_buffer,
            "single_position_weight_after": single_after,
            "lot_upgrade_ratio": (
                _safe_float(one_lot_cost, default=0.0) / max(float(strategy_target_notional), 1e-12)
                if _safe_float(one_lot_cost, default=0.0) > 0.0
                else pd.NA
            ),
            "retail_one_lot_position_cap": float(
                runner.capital_profile.get("retail_one_lot_position_cap", runner.capital_profile.get("retail_single_position_cap", 0.40))
                or runner.capital_profile.get("retail_single_position_cap", 0.40)
            ),
            "retail_min_entry_matrix_score": float(
                runner.capital_profile.get("retail_min_entry_matrix_score", 0.0) or 0.0
            ),
            "position_state": order.get("position_state", ""),
            "entry_matrix_score": order.get("entry_matrix_score", pd.NA),
            "entry_alpha_score": order.get("entry_alpha_score", pd.NA),
            "entry_timing_score": order.get("entry_timing_score", pd.NA),
            "entry_liquidity_score": order.get("entry_liquidity_score", pd.NA),
            "alpha_quality_score": order.get("alpha_quality_score", pd.NA),
            "surge_capture_score": order.get("surge_capture_score", pd.NA),
            "follow_through_score": order.get("follow_through_score", pd.NA),
            "exhaustion_score": order.get("exhaustion_score", pd.NA),
            "entry_success_probability": order.get("entry_success_probability", pd.NA),
            "entry_size_tier": order.get("entry_size_tier", ""),
            "planned_entry_lots": order.get("planned_entry_lots", pd.NA),
            "empirical_distribution_score": order.get("empirical_distribution_score", pd.NA),
            "final_entry_score": order.get("final_entry_score", pd.NA),
            "tail_risk_proxy": order.get("tail_risk_proxy", pd.NA),
            "trend_direction_score": order.get("trend_direction_score", pd.NA),
            "peak_decay_score": order.get("peak_decay_score", pd.NA),
            "profit_protection_pressure": order.get("profit_protection_pressure", pd.NA),
            "dynamic_giveback_limit": order.get("dynamic_giveback_limit", pd.NA),
            "future_loss_risk_score": order.get("future_loss_risk_score", pd.NA),
            "downtrend_decay_score": order.get("downtrend_decay_score", pd.NA),
            "post_entry_failure_score": order.get("post_entry_failure_score", pd.NA),
            "strategy_logic_version": order.get("strategy_logic_version", ""),
            "cabinet_native_final_score": order.get("cabinet_native_final_score", pd.NA),
            "cabinet_base_entry_score": order.get("cabinet_base_entry_score", pd.NA),
            "cabinet_strict_entry_score": order.get("cabinet_strict_entry_score", pd.NA),
            "cabinet_proxy_entry_score": order.get("cabinet_proxy_entry_score", pd.NA),
            "cabinet_timing_score": order.get("cabinet_timing_score", pd.NA),
            "cabinet_liquidity_health_score": order.get("cabinet_liquidity_health_score", pd.NA),
            "cabinet_risk_safety_score": order.get("cabinet_risk_safety_score", pd.NA),
            "cabinet_hold_support_score": order.get("cabinet_hold_support_score", pd.NA),
            "cabinet_entry_thesis": order.get("cabinet_entry_thesis", ""),
            "cabinet_entry_thesis_support": order.get("cabinet_entry_thesis_support", pd.NA),
            "mainline_v3_one_lot_cash_required": order.get("mainline_v3_one_lot_cash_required", pd.NA),
            "mainline_v3_one_lot_weight": order.get("mainline_v3_one_lot_weight", pd.NA),
            "mainline_v3_lot_feasible": order.get("mainline_v3_lot_feasible", pd.NA),
            "retail_action": str(retail_action),
            "retail_block_reason": str(retail_block_reason),
            "capital_profile": str(runner.capital_profile.get("name", "")),
        }
    )
