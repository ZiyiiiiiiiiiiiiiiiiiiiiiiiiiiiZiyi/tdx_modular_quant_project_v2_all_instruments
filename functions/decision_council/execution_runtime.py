"""Order registration and execution runtime for governance backtests."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from functions.execution.cost_model import cost_kwargs_from_profile, estimate_trade_costs
from functions.execution.order_simulator import simulate_order_book
from functions.execution.execution_rules import open_price_limit_blocked
from functions.execution.security_trading_rules import legal_buy_quantity, trading_rule_for
from functions.decision_council.mainline_v2 import is_mainline_v3_version
from functions.decision_council.exit_reason_contract import is_full_liquidation_reason
from functions.decision_council.cash_reservation_ledger import (
    CashReservationLedger,
)


@dataclass
class Position:
    shares: float
    acquired_date: pd.Timestamp


def authoritative_action_plan_buy_shares(
    order,
    *,
    strategy_logic_version: str,
    minimum_buy_quantity: float,
) -> float | None:
    """Return the immutable ActionPlan buy quantity when it has authority.

    ``None`` means the order is outside the cabinet-native ActionPlan contract.
    A selected V3 buy without a positive integer lot count is a broken lineage
    contract and must fail closed instead of silently becoming one lot.
    """
    if not (
        is_mainline_v3_version(strategy_logic_version)
        and str(order.get("side", "")).strip().lower() == "buy"
        and str(order.get("action_plan_selected", False)).strip().lower()
        in {"true", "1"}
    ):
        return None
    raw_lots = pd.to_numeric(pd.Series([order.get("planned_entry_lots")]), errors="coerce").iloc[0]
    if pd.isna(raw_lots) or float(raw_lots) <= 0.0 or abs(float(raw_lots) - round(float(raw_lots))) > 1e-9:
        raise RuntimeError("selected ActionPlan buy is missing a positive integer planned_entry_lots")
    minimum = float(minimum_buy_quantity)
    if minimum <= 0.0:
        raise RuntimeError("selected ActionPlan buy has an invalid minimum buy quantity")
    return float(int(round(float(raw_lots))) * int(round(minimum)))


def execute_pending(runner, date, daily):
    active = runner.engine.pending_orders.orders
    active = active[
        active["status"].isin(["pending", "pending_locked"])
        & (pd.to_datetime(active["created_date"], errors="coerce") < pd.Timestamp(date))
    ].copy()
    if active.empty:
        return
    market = daily.set_index("symbol", drop=False)
    replacement_sell_filled = filled_replacement_sell_pair_ids(
        runner.engine.pending_orders.orders
    )
    rows = []
    blocked_symbols = set()
    blocked_reasons = {}
    fill_map = {}
    profile = dict(getattr(runner, "capital_profile", {}) or {})
    max_new_names = max(int(profile.get("scap_max_daily_new_names", 2) or 2), 1)
    max_new_exposure_ratio = min(
        max(float(profile.get("scap_max_daily_new_exposure_ratio", 0.35) or 0.35), 0.0),
        1.0,
    )
    prior_exposure = getattr(runner, "exposure_rows", [])
    nominal_nav = float(
        prior_exposure[-1].get("nominal_nav", runner.initial_cash)
        if prior_exposure
        else runner.initial_cash
    )
    max_new_notional = max(nominal_nav * max_new_exposure_ratio, 0.0)
    prior_authorized_exposure = float(
        prior_exposure[-1].get("authorized_exposure_max", 1.0)
        if prior_exposure
        else 1.0
    )
    market_by_symbol = daily.set_index("symbol", drop=False)
    invested_at_open = 0.0
    for held_symbol, position in runner.positions.items():
        if held_symbol in market_by_symbol.index:
            held_quote = market_by_symbol.loc[held_symbol]
            held_open = float(
                pd.to_numeric(
                    pd.Series([held_quote.get("open_nominal", held_quote.get("close_nominal", 0.0))]),
                    errors="coerce",
                ).fillna(0.0).iloc[0]
            )
            invested_at_open += max(float(position.shares), 0.0) * max(held_open, 0.0)
    authorization_buy_room = max(
        prior_authorized_exposure * nominal_nav - invested_at_open,
        0.0,
    )
    max_new_notional = min(max_new_notional, authorization_buy_room)
    accepted_new_names = 0
    accepted_buy_notional = 0.0
    session_ordinals = getattr(runner, "_decision_session_ordinal", {})
    current_ordinal = session_ordinals.get(pd.Timestamp(date))
    for _, order in active.sort_values(["priority", "created_date"]).iterrows():
        symbol = str(order["symbol"])
        execution_policy = str(order.get("order_execution_policy", "")).strip().lower()
        created_ordinal = session_ordinals.get(pd.Timestamp(order["created_date"]))
        signal_age_sessions = (
            int(current_ordinal - created_ordinal)
            if current_ordinal is not None and created_ordinal is not None
            else int(order.get("retry_count", 0) or 0) + 1
        )
        order_index = runner.engine.pending_orders.orders.index[
            runner.engine.pending_orders.orders["order_id"].astype(str).eq(str(order["order_id"]))
        ]
        if len(order_index):
            runner.engine.pending_orders.orders.at[
                order_index[0], "signal_age_sessions"
            ] = signal_age_sessions
        maximum_age_sessions = max(int(order.get("maximum_age_sessions", 1) or 1), 1)
        if (
            str(order["side"]).lower() == "buy"
            and execution_policy == "monthly_plan_window"
            and signal_age_sessions > maximum_age_sessions
        ):
            blocked_symbols.add(symbol)
            blocked_reasons[symbol] = "monthly_plan_signal_expired"
            continue
        if symbol not in market.index:
            blocked_symbols.add(symbol)
            blocked_reasons[symbol] = "market_data_unavailable"
            continue
        quote = market.loc[symbol]
        pair_id = str(order.get("replacement_pair_id", "") or "")
        pair_leg = str(order.get("replacement_pair_leg", "") or "").lower()
        if (
            pair_id
            and pair_leg == "buy"
            and pair_id in replacement_sell_filled
            and not replacement_pair_still_valid(order, market)
        ):
            blocked_symbols.add(symbol)
            blocked_reasons[symbol] = "replacement_candidate_no_longer_superior"
            continue
        price = float(quote["open_nominal"])
        requested = float(order["remaining_shares"])
        if str(order["side"]).lower() == "buy" and execution_policy == "monthly_plan_window":
            requested_notional = max(price * requested, 0.0)
            is_new_name = symbol not in runner.positions
            execution_permission_now = bool(quote["is_trading"]) and not open_price_limit_blocked(
                side=order["side"],
                open_price=price,
                limit_up_price=quote.get("limit_up_price"),
                limit_down_price=quote.get("limit_down_price"),
            )
            exceeds_name_limit = is_new_name and accepted_new_names >= max_new_names
            exceeds_exposure_limit = (
                accepted_buy_notional > 0.0
                and accepted_buy_notional + requested_notional > max_new_notional + 1e-8
            )
            if exceeds_name_limit or exceeds_exposure_limit:
                blocked_symbols.add(symbol)
                blocked_reasons[symbol] = "monthly_plan_deployment_limit"
                continue
            if execution_permission_now:
                accepted_buy_notional += requested_notional
                if is_new_name:
                    accepted_new_names += 1
        if str(order["side"]) == "sell":
            position = runner.positions.get(symbol)
            requested = min(requested, position.shares if position else 0.0)
        row = {
            "symbol": symbol,
            "signal_date": pd.Timestamp(order["created_date"]),
            "decision_timestamp": pd.Timestamp(order["created_date"]) + pd.Timedelta(hours=15),
            "scheduled_execution_date": runner.trading_calendar.next_session(order["created_date"]),
            "next_trading_day": pd.Timestamp(date),
            "trade_date": date,
            "execution_price_basis": "next_available_trading_day_open_nominal",
            "side": order["side"],
            "target_shares": requested,
            "current_position_shares": (
                float(runner.positions[symbol].shares) if symbol in runner.positions else 0.0
            ),
            "price": price,
            "market_amount": float(pd.to_numeric(pd.Series([quote.get("amount", 0.0)]), errors="coerce").fillna(0.0).iloc[0]),
            "same_day_sell_blocked": bool(
                str(order["side"]) == "sell"
                and symbol in runner.positions
                and runner.positions[symbol].acquired_date >= pd.Timestamp(date)
            ),
            "price_limit_blocked_flag": open_price_limit_blocked(
                side=order["side"],
                open_price=price,
                limit_up_price=quote.get("limit_up_price"),
                limit_down_price=quote.get("limit_down_price"),
            ),
            "execution_feasibility_basis": "open_and_prior_close_limits_only",
            "suspension_blocked_flag": not bool(quote["is_trading"]),
            "order_id": order["order_id"],
            "decision_id": order["decision_id"],
            "reason": order["reason"],
            "order_execution_policy": order.get("order_execution_policy", ""),
            "maximum_age_sessions": order.get("maximum_age_sessions", pd.NA),
            "signal_age_sessions": signal_age_sessions,
            "origin_reason": order.get("origin_reason", order.get("reason", "")),
            "latest_reason": order.get("latest_reason", order.get("reason", "")),
            "highest_priority_reason": order.get(
                "highest_priority_reason", order.get("reason", "")
            ),
            "reason_history": order.get("reason_history", order.get("reason", "")),
            "reason_schema_version": order.get("reason_schema_version", ""),
            "position_state": order.get("position_state", ""),
            "position_exit_reason": order.get("position_exit_reason", ""),
            "liquidation_intent": str(
                order.get("liquidation_intent", False)
            ).strip().lower() in {"true", "1"},
            "add_layer": order.get("add_layer", pd.NA),
            "add_allowed": order.get("add_allowed", False),
            "add_block_reason": order.get("add_block_reason", ""),
            "add_decision_type": order.get("add_decision_type", ""),
            "unified_action_selected": order.get("unified_action_selected", ""),
            "unified_action_proposals": order.get("unified_action_proposals", ""),
            "unified_action_vetoed": order.get("unified_action_vetoed", ""),
            "unified_action_conflict_count": order.get(
                "unified_action_conflict_count", 0
            ),
            "unified_action_contract": order.get("unified_action_contract", ""),
            "action_plan_id": order.get("action_plan_id", ""),
            "action_proposal_id": order.get("action_proposal_id", ""),
            "sizing_contract_id": order.get("sizing_contract_id", ""),
            "authorized_lots": order.get("authorized_lots", pd.NA),
            "action_plan_selected": order.get("action_plan_selected", False),
            "action_plan_contract": order.get("action_plan_contract", ""),
            "scap_v31_authority_tier": order.get(
                "scap_v31_authority_tier", ""
            ),
            "scap_v31_authority_contract": order.get(
                "scap_v31_authority_contract", ""
            ),
            "cash_reservation_id": order.get("cash_reservation_id", ""),
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
            "orderflow_candidate_score": order.get("orderflow_candidate_score", pd.NA),
            "reversal_entry_score": order.get("reversal_entry_score", pd.NA),
            "breakout_gate_score": order.get("breakout_gate_score", pd.NA),
            "trend_hold_score": order.get("trend_hold_score", pd.NA),
            "strategy_logic_version": order.get("strategy_logic_version", ""),
            "mainline_v3_score_authority": order.get(
                "mainline_v3_score_authority", ""
            ),
            "mainline_v3_score_authority_version": order.get(
                "mainline_v3_score_authority_version", ""
            ),
            "mainline_v3_selection_evaluated": order.get(
                "mainline_v3_selection_evaluated", pd.NA
            ),
            "cabinet_native_final_score": order.get("cabinet_native_final_score", pd.NA),
            "mainline_v3_score_authority": order.get(
                "mainline_v3_score_authority", ""
            ),
            "mainline_v3_score_authority_version": order.get(
                "mainline_v3_score_authority_version", ""
            ),
            "mainline_v3_selection_evaluated": order.get(
                "mainline_v3_selection_evaluated", pd.NA
            ),
            "v31_reliability_score": order.get("v31_reliability_score", pd.NA),
            "v31_reliability_score_coverage": order.get("v31_reliability_score_coverage", pd.NA),
            "v31_reliability_contract": order.get("v31_reliability_contract", pd.NA),
            "v31_calibration_window": order.get("v31_calibration_window", pd.NA),
            "v31_score_formula": order.get("v31_score_formula", pd.NA),
            "v31_score_authority": order.get("v31_score_authority", pd.NA),
            "v31_strict_entry_paper_only": order.get("v31_strict_entry_paper_only", pd.NA),
            "monthly_lgbm_raw_score": order.get("monthly_lgbm_raw_score", pd.NA),
            "monthly_lgbm_rank_percentile": order.get("monthly_lgbm_rank_percentile", pd.NA),
            "hybrid_final_score": order.get("hybrid_final_score", pd.NA),
            "hybrid_ml_weight": order.get("hybrid_ml_weight", pd.NA),
            "hybrid_fusion_status": order.get("hybrid_fusion_status", ""),
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
            "comparable_value_horizon_days": order.get("comparable_value_horizon_days", pd.NA),
            "comparable_expected_alpha": order.get("comparable_expected_alpha", pd.NA),
            "comparable_alpha_lcb": order.get("comparable_alpha_lcb", pd.NA),
            "comparable_value_contract": order.get("comparable_value_contract", ""),
            "replacement_pair_id": order.get("replacement_pair_id", ""),
            "replacement_paired_symbol": order.get("replacement_paired_symbol", ""),
            "replacement_pair_leg": order.get("replacement_pair_leg", ""),
            "replacement_horizon_days": order.get("replacement_horizon_days", pd.NA),
            "replacement_expected_net_edge": order.get("replacement_expected_net_edge", pd.NA),
            "replacement_lcb_net_edge": order.get("replacement_lcb_net_edge", pd.NA),
            "replacement_cost_rate": order.get("replacement_cost_rate", pd.NA),
            "replacement_contract": order.get("replacement_contract", ""),
        }
        rows.append(row)
    if not rows:
        runner.engine.settle_pending_orders(date, blocked_symbols=blocked_symbols)
        return
    simulated = simulate_order_book(
        pd.DataFrame(rows),
        cost_profile=runner.capital_profile,
    )
    processed_fill_ids = {
        str(row.get("fill_id", "") or "")
        for row in getattr(runner, "execution_rows", [])
    }
    for _, fill in simulated.iterrows():
        symbol = str(fill["symbol"])
        order_id = str(fill["order_id"])
        pair_id = str(fill.get("replacement_pair_id", "") or "")
        pair_leg = str(fill.get("replacement_pair_leg", "") or "").lower()
        if not replacement_pair_leg_authorized(pair_id, pair_leg, replacement_sell_filled):
            blocked_symbols.add(symbol)
            blocked_reasons[symbol] = "paired_sell_not_filled"
            continue
        if fill["execution_status"] != "filled":
            blocked_symbols.add(symbol)
            continue
        shares = float(fill["executed_shares"])
        notional = float(fill["trade_notional"])
        cost = float(fill["total_cost"])
        fill_id = (
            f"{order_id}|{pd.Timestamp(date).date()}|"
            f"{str(fill['side']).lower()}|{float(fill['price']):.6f}|{shares:.6f}"
        )
        if fill_id in processed_fill_ids:
            fill_map[order_id] = {"shares": shares, "fill_id": fill_id}
            continue
        if str(fill["side"]) == "buy":
            max_positions = getattr(runner, "_max_positions_override", None)
            if (
                max_positions is not None
                and symbol not in runner.positions
                and len(runner.positions) >= int(max_positions)
            ):
                blocked_symbols.add(symbol)
                blocked_reasons[symbol] = "position_limit"
                continue
            affordable = max(runner.cash - cost, 0.0)
            affordable_quantity = legal_buy_quantity(
                symbol,
                affordable // float(fill["price"]),
                trade_date=date,
            )
            shares = min(shares, affordable_quantity)
            if shares <= 0:
                continue
            recalculated = estimate_trade_costs(
                pd.DataFrame([{**fill.to_dict(), "target_shares": shares}]),
                **cost_kwargs_from_profile(runner.capital_profile),
            )
            notional = float(recalculated.iloc[0]["trade_notional"])
            cost = float(recalculated.iloc[0]["total_cost"])
            runner.cash -= notional + cost
            current = runner.positions.get(symbol)
            runner.positions[symbol] = Position(
                shares=(current.shares if current else 0.0) + shares,
                acquired_date=pd.Timestamp(date),
            )
            runner.holding_days.setdefault(symbol, 0)
            runner._update_lifecycle_on_buy(
                symbol,
                date=date,
                price=float(fill["price"]),
                shares=shares,
                current=current,
                signal=fill,
            )
        else:
            current = runner.positions.get(symbol)
            shares = min(shares, current.shares if current else 0.0)
            if shares <= 0:
                continue
            runner.cash += notional - cost
            remaining = current.shares - shares
            if remaining <= 1e-12:
                runner.positions.pop(symbol, None)
                runner.holding_days.pop(symbol, None)
                runner.position_lifecycle.pop(symbol, None)
                for confirmation_key in [
                    key
                    for key in runner.position_exit_confirmations
                    if str(key).startswith(f"{symbol}|")
                ]:
                    runner.position_exit_confirmations.pop(
                        confirmation_key, None
                    )
                runner._register_position_cooldown(symbol, date=date, reason=str(fill.get("reason", "")))
            else:
                runner.positions[symbol] = Position(remaining, current.acquired_date)
            if pair_id and pair_leg == "sell":
                replacement_sell_filled.add(pair_id)
        fill_map[order_id] = {"shares": shares, "fill_id": fill_id}
        record = fill.to_dict()
        record.update({"executed_shares": shares, "trade_notional": notional, "total_cost": cost, "order_id": order_id, "fill_id": fill_id})
        runner.execution_rows.append(record)
        processed_fill_ids.add(fill_id)
        if str(fill["side"]) == "sell" and str(fill.get("reason")) == "alpha_collapse_consensus":
            runner._pending_alpha_collapse_exits.append(
                {
                    "decision_id": fill.get("decision_id"),
                    "symbol": symbol,
                    "exit_date": pd.Timestamp(date),
                    "exit_price": float(fill["price"]),
                }
            )
    runner.engine.settle_pending_orders(
        date,
        fills=fill_map,
        blocked_symbols=blocked_symbols,
        blocked_reasons=blocked_reasons,
    )
    max_positions = getattr(runner, "_max_positions_override", None)
    if max_positions is not None and len(runner.positions) > int(max_positions):
        raise RuntimeError(
            "governance position limit invariant failed after execution: "
            f"positions={len(runner.positions)}, max_positions={int(max_positions)}"
        )


def replacement_pair_leg_authorized(pair_id: str, pair_leg: str, filled_sell_pair_ids) -> bool:
    """A paired buy is executable only after its paired sale has filled."""
    normalized_id = str(pair_id or "")
    normalized_leg = str(pair_leg or "").strip().lower()
    if not normalized_id or normalized_leg != "buy":
        return True
    return normalized_id in {str(value) for value in filled_sell_pair_ids}


def filled_replacement_sell_pair_ids(orders: pd.DataFrame | None) -> set[str]:
    """Recover durable sell-leg authority from the persistent order book."""
    if orders is None or orders.empty:
        return set()
    required = {"replacement_pair_id", "replacement_pair_leg", "status"}
    if not required.issubset(orders.columns):
        return set()
    pair_ids = orders.loc[
        orders["replacement_pair_leg"].fillna("").astype(str).str.lower().eq("sell")
        & orders["status"].fillna("").astype(str).str.lower().eq("filled"),
        "replacement_pair_id",
    ].fillna("").astype(str)
    return {value for value in pair_ids if value}


def replacement_pair_still_valid(order: pd.Series | dict, market: pd.DataFrame) -> bool:
    """Revalidate a carried buy in the original horizon/return unit when possible."""
    challenger = str(order.get("symbol", "") or "")
    held = str(order.get("replacement_paired_symbol", "") or "")
    if not challenger or not held or challenger not in market.index or held not in market.index:
        return True
    challenger_row = market.loc[challenger]
    held_row = market.loc[held]
    challenger_lcb = pd.to_numeric(
        pd.Series([challenger_row.get("comparable_alpha_lcb")]), errors="coerce"
    ).iloc[0]
    held_expected = pd.to_numeric(
        pd.Series([held_row.get("comparable_expected_alpha")]), errors="coerce"
    ).iloc[0]
    cost = pd.to_numeric(
        pd.Series([order.get("replacement_cost_rate")]), errors="coerce"
    ).iloc[0]
    if pd.isna(challenger_lcb) or pd.isna(held_expected) or pd.isna(cost):
        return True
    return float(challenger_lcb - held_expected - cost) > 0.0

def prune_empty_positions(runner, *, min_shares: float = 1e-9) -> None:
    empty_symbols = [
        symbol
        for symbol, position in runner.positions.items()
        if position is None or float(position.shares) <= float(min_shares)
    ]
    for symbol in empty_symbols:
        runner.positions.pop(symbol, None)
        runner.holding_days.pop(symbol, None)


def register_orders(runner, orders, daily, nominal_nav):
    diagnostics = {
        "retail_order_count": 0,
        "retail_upgraded_to_one_lot_count": 0,
        "retail_blocked_count": 0,
        "retail_lot_cash_insufficient_count": 0,
        "retail_state_block_count": 0,
        "retail_no_price_count": 0,
        "zero_lot_order_count": 0,
        "zero_lot_buy_order_count": 0,
        "zero_lot_sell_order_count": 0,
        "atomic_replacement_registered_count": 0,
        "atomic_replacement_rejected_count": 0,
        "atomic_replacement_rejection_reasons": "",
    }
    if orders.empty:
        return diagnostics
    if runner._retail_lot_adapter_enabled:
        orders = runner._sort_retail_orders(orders)
    prices = daily.set_index("symbol")["close_nominal"]
    cash_ledger = CashReservationLedger(
        cash_amount=float(runner.cash),
        minimum_buffer=float(
            getattr(runner, "capital_profile", {}).get(
                "min_cash_buffer", 0.0
            )
            or 0.0
        ),
    )
    prepared_payloads = []
    conditional_pair_cash: dict[str, float] = {}
    atomic_rejection_reasons: list[str] = []
    for _, order in orders.iterrows():
        symbol = str(order["symbol"])
        decision_value = order.get("decision_date")
        if decision_value is None or pd.isna(decision_value):
            decision_value = runner.trading_calendar.previous_session(order["execution_date"])
        decision_date = pd.Timestamp(decision_value)
        actual_execution_date = runner.trading_calendar.next_session(decision_date)
        mark = runner.price_ledger.mark(symbol, as_of=decision_date)
        if symbol in prices.index:
            order_price = float(prices.at[symbol])
        elif mark is not None:
            order_price = float(mark.price)
        else:
            runner._record_retail_execution_diagnostic(
                order=order,
                nominal_nav=nominal_nav,
                price=pd.NA,
                one_lot_cost=pd.NA,
                strategy_target_notional=abs(float(order["delta_weight"])) * float(nominal_nav),
                adjusted_target_notional=0.0,
                target_shares=0.0,
                available_cash=cash_ledger.available(),
                retail_action="blocked_no_price",
                retail_block_reason="missing_price",
            )
            diagnostics["retail_no_price_count"] += 1
            diagnostics["retail_blocked_count"] += 1
            continue
        rule = trading_rule_for(symbol, trade_date=actual_execution_date)
        side = str(order["side"]).strip().lower()
        shares = abs(float(order["delta_weight"])) * float(nominal_nav) / order_price
        current_position = getattr(runner, "positions", {}).get(symbol)
        target_weight = pd.to_numeric(pd.Series([order.get("target_weight")]), errors="coerce").iloc[0]
        if (
            side == "sell" and current_position is not None
            and (
                str(order.get("liquidation_intent", False)).strip().lower()
                in {"true", "1"}
                or is_full_liquidation_reason(order.get("reason", ""))
                or (pd.notna(target_weight) and float(target_weight) <= 1e-12)
            )
        ):
            # Full liquidation is defined by an explicit exit intent or a zero
            # target.  Safety deleveraging is a partial risk-budget adjustment
            # and must remain subject to board lot-size quantisation.
            shares = float(current_position.shares)
        if side == "buy":
            shares = legal_buy_quantity(symbol, shares, trade_date=actual_execution_date)
        elif shares == float(current_position.shares if current_position is not None else -1.0) and rule.odd_lot_full_exit_allowed:
            shares = float(int(shares))
        elif rule.board_type == "star":
            shares = float(int(shares)) if shares >= rule.minimum_buy_quantity else 0.0
        else:
            shares = float(int(shares // rule.standard_sell_step) * rule.standard_sell_step)
        action_plan_shares = authoritative_action_plan_buy_shares(
            order,
            strategy_logic_version=getattr(runner, "strategy_logic_version", ""),
            minimum_buy_quantity=rule.minimum_buy_quantity,
        )
        if action_plan_shares is not None:
            # The unique ActionPlan already solved integer lots, exact cash and
            # portfolio risk.  Execution may block the order on new factual
            # constraints, but it must never resize it without re-authorization.
            shares = legal_buy_quantity(
                symbol,
                action_plan_shares,
                trade_date=actual_execution_date,
            )
            if abs(float(shares) - float(action_plan_shares)) > 1e-9:
                raise RuntimeError(
                    "selected ActionPlan buy quantity is not board-lot legal: "
                    f"symbol={symbol}, planned={action_plan_shares}, legal={shares}"
                )
        strategy_target_notional = abs(float(order["delta_weight"])) * float(nominal_nav)
        retail_action = "unchanged"
        retail_block_reason = ""
        one_lot_cost = float(order_price) * float(rule.minimum_buy_quantity)
        one_lot_cash_required = runner._retail_cash_required(
            side=str(order["side"]),
            price=order_price,
            shares=float(rule.minimum_buy_quantity),
        )
        pair_id = str(order.get("replacement_pair_id", "") or "")
        pair_leg = str(order.get("replacement_pair_leg", "") or "").lower()
        if runner._retail_lot_adapter_enabled and str(order["side"]) == "buy":
            diagnostics["retail_order_count"] += 1
            conditional_credit = (
                float(conditional_pair_cash.get(pair_id, 0.0))
                if pair_id and pair_leg == "buy"
                else 0.0
            )
            adapter_reserved_cash = float(runner.cash) - cash_ledger.available(
                conditional_credit=conditional_credit
            )
            shares, retail_action, retail_block_reason = runner._adapt_retail_buy_order(
                order=order,
                strategy_target_notional=strategy_target_notional,
                order_price=order_price,
                nominal_nav=nominal_nav,
                reserved_cash=adapter_reserved_cash,
                initial_shares=shares,
                one_lot_cash_required=one_lot_cash_required,
            )
            if retail_action in {"upgraded_to_one_lot", "upgraded_to_one_lot_strong"}:
                diagnostics["retail_upgraded_to_one_lot_count"] += 1
            if retail_block_reason:
                diagnostics["retail_blocked_count"] += 1
                if retail_block_reason in {"lot_size_cash_insufficient", "cash_buffer"}:
                    diagnostics["retail_lot_cash_insufficient_count"] += 1
                if retail_block_reason == "position_state":
                    diagnostics["retail_state_block_count"] += 1
            runner._record_retail_execution_diagnostic(
                order=order,
                nominal_nav=nominal_nav,
                price=order_price,
                one_lot_cost=one_lot_cost,
                one_lot_cash_required=one_lot_cash_required,
                strategy_target_notional=strategy_target_notional,
                adjusted_target_notional=float(shares) * float(order_price),
                target_shares=shares,
                available_cash=cash_ledger.available(),
                retail_action=retail_action,
                retail_block_reason=retail_block_reason,
            )
        if shares <= 0:
            side = str(order["side"]).strip().lower()
            zero_lot_reason = f"{side}_weight_change_below_one_lot"
            diagnostics["zero_lot_order_count"] += 1
            diagnostics[f"zero_lot_{side}_order_count"] += 1
            if not retail_block_reason:
                diagnostics["retail_blocked_count"] += 1
                runner._record_retail_execution_diagnostic(
                    order=order,
                    nominal_nav=nominal_nav,
                    price=order_price,
                    one_lot_cost=one_lot_cost,
                    one_lot_cash_required=one_lot_cash_required,
                    strategy_target_notional=strategy_target_notional,
                    adjusted_target_notional=0.0,
                    target_shares=0.0,
                    available_cash=cash_ledger.available(),
                    retail_action="blocked_zero_lot",
                    retail_block_reason=zero_lot_reason,
                )
            continue
        if pair_id and pair_leg == "sell":
            sell_costs = estimate_trade_costs(
                pd.DataFrame(
                    [
                        {
                            "symbol": symbol,
                            "trade_date": actual_execution_date,
                            "side": "sell",
                            "price": order_price,
                            "target_shares": shares,
                        }
                    ]
                ),
                **cost_kwargs_from_profile(runner.capital_profile),
            ).iloc[0]
            conditional_pair_cash[pair_id] = max(
                float(sell_costs.get("trade_notional", 0.0))
                - float(sell_costs.get("total_cost", 0.0)),
                0.0,
            )
        if runner._retail_lot_adapter_enabled and str(order["side"]) == "buy":
            reservation_id = (
                f"{order.get('decision_id', '')}|{symbol}|buy|"
                f"{order.get('reason', '')}|{pair_id}"
            )
            cash_ledger.reserve(
                reservation_id,
                runner._retail_cash_required(
                side=str(order["side"]),
                price=order_price,
                shares=shares,
                ),
                funding_type=(
                    "conditional_replacement" if pair_id else "cash"
                ),
                pair_id=pair_id,
            )
            order = order.copy()
            order["_cash_reservation_id"] = reservation_id
        order_reason = str(order.get("reason", "") or "")
        monthly_normal_buy = is_monthly_normal_buy(
            side=order.get("side", ""),
            order_reason=order_reason,
            rebalance_frequency=getattr(
                runner, "portfolio_normal_rebalance_frequency", ""
            ),
        )
        if monthly_normal_buy:
            order_reason = "monthly_normal_buy"
        payload = {
            "decision_id": order["decision_id"],
            "symbol": symbol,
            "side": order["side"],
            "reason": order_reason,
            "origin_reason": order_reason,
            "latest_reason": order_reason,
            "highest_priority_reason": order.get(
                "highest_priority_reason", order_reason
            ),
            "reason_history": order_reason,
            "reason_schema_version": order.get(
                "reason_schema_version", "scap_exit_reason_contract_v1"
            ),
            "priority": int(order["priority"]),
            "created_date": decision_date,
            "scheduled_execution_date": actual_execution_date,
            "order_execution_policy": (
                "monthly_plan_window" if monthly_normal_buy else "next_session_only"
            ),
            "maximum_age_sessions": (
                int(runner.capital_profile.get("scap_monthly_plan_execution_window_sessions", 5) or 5)
                if monthly_normal_buy
                else 1
            ),
            "signal_age_sessions": 0,
            "target_shares": shares,
            "position_state": order.get("position_state", ""),
            "position_exit_reason": order.get("position_exit_reason", ""),
            "liquidation_intent": str(
                order.get("liquidation_intent", False)
            ).strip().lower() in {"true", "1"},
            "add_layer": order.get("add_layer", pd.NA),
            "add_allowed": order.get("add_allowed", False),
            "add_block_reason": order.get("add_block_reason", ""),
            "add_decision_type": order.get("add_decision_type", ""),
            "unified_action_selected": order.get("unified_action_selected", ""),
            "unified_action_proposals": order.get("unified_action_proposals", ""),
            "unified_action_vetoed": order.get("unified_action_vetoed", ""),
            "unified_action_conflict_count": order.get(
                "unified_action_conflict_count", 0
            ),
            "unified_action_contract": order.get("unified_action_contract", ""),
            "action_plan_id": order.get("action_plan_id", ""),
            "action_proposal_id": order.get("action_proposal_id", ""),
            "sizing_contract_id": order.get("sizing_contract_id", ""),
            "authorized_lots": order.get("authorized_lots", pd.NA),
            "action_plan_selected": order.get("action_plan_selected", False),
            "action_plan_contract": order.get("action_plan_contract", ""),
            "scap_v31_authority_tier": order.get(
                "scap_v31_authority_tier", ""
            ),
            "scap_v31_authority_contract": order.get(
                "scap_v31_authority_contract", ""
            ),
            "cash_reservation_id": order.get(
                "_cash_reservation_id", order.get("cash_reservation_id", "")
            ),
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
            "v31_reliability_score": order.get("v31_reliability_score", pd.NA),
            "v31_reliability_score_coverage": order.get("v31_reliability_score_coverage", pd.NA),
            "v31_reliability_contract": order.get("v31_reliability_contract", pd.NA),
            "v31_calibration_window": order.get("v31_calibration_window", pd.NA),
            "v31_score_formula": order.get("v31_score_formula", pd.NA),
            "v31_score_authority": order.get("v31_score_authority", pd.NA),
            "v31_strict_entry_paper_only": order.get("v31_strict_entry_paper_only", pd.NA),
            "monthly_lgbm_raw_score": order.get("monthly_lgbm_raw_score", pd.NA),
            "monthly_lgbm_rank_percentile": order.get("monthly_lgbm_rank_percentile", pd.NA),
            "hybrid_final_score": order.get("hybrid_final_score", pd.NA),
            "hybrid_ml_weight": order.get("hybrid_ml_weight", pd.NA),
            "hybrid_fusion_status": order.get("hybrid_fusion_status", ""),
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
            "comparable_value_horizon_days": order.get("comparable_value_horizon_days", pd.NA),
            "comparable_expected_alpha": order.get("comparable_expected_alpha", pd.NA),
            "comparable_alpha_lcb": order.get("comparable_alpha_lcb", pd.NA),
            "comparable_value_contract": order.get("comparable_value_contract", ""),
            "replacement_pair_id": order.get("replacement_pair_id", ""),
            "replacement_paired_symbol": order.get("replacement_paired_symbol", ""),
            "replacement_pair_leg": order.get("replacement_pair_leg", ""),
            "replacement_horizon_days": order.get("replacement_horizon_days", pd.NA),
            "replacement_expected_net_edge": order.get("replacement_expected_net_edge", pd.NA),
            "replacement_lcb_net_edge": order.get("replacement_lcb_net_edge", pd.NA),
            "replacement_cost_rate": order.get("replacement_cost_rate", pd.NA),
            "replacement_contract": order.get("replacement_contract", ""),
        }
        prepared_payloads.append(payload)
    paired_payloads: dict[str, list[dict]] = {}
    ordinary_payloads = []
    for payload in prepared_payloads:
        pair_id = str(payload.get("replacement_pair_id", "") or "")
        if pair_id:
            paired_payloads.setdefault(pair_id, []).append(payload)
        else:
            ordinary_payloads.append(payload)
    for payload in ordinary_payloads:
        if str(payload.get("side", "")).lower() == "sell":
            runner.engine.pending_orders.upsert_sell_intent(payload)
        else:
            runner.engine.pending_orders.add_order(payload)
    for pair_id, pair_payloads in paired_payloads.items():
        legs = {
            str(payload.get("replacement_pair_leg", "") or "").lower()
            for payload in pair_payloads
        }
        if len(pair_payloads) != 2 or legs != {"sell", "buy"}:
            diagnostics["atomic_replacement_rejected_count"] += 1
            atomic_rejection_reasons.append(f"{pair_id}:incomplete_prepared_pair")
            continue
        buy_payload = next(
            payload
            for payload in pair_payloads
            if str(payload.get("replacement_pair_leg", "")).lower() == "buy"
        )
        buy_cash_required = runner._retail_cash_required(
            side="buy",
            price=float(prices.at[str(buy_payload["symbol"])]),
            shares=float(buy_payload["target_shares"]),
        )
        reservation_id = str(buy_payload.get("cash_reservation_id", "") or "")
        conditional_available = cash_ledger.available(
            excluding_reservation_id=reservation_id,
            conditional_credit=float(conditional_pair_cash.get(pair_id, 0.0)),
        )
        min_buffer = float(
            runner.capital_profile.get("min_cash_buffer", 0.0) or 0.0
        )
        if buy_cash_required > max(conditional_available - min_buffer, 0.0) + 1e-12:
            diagnostics["atomic_replacement_rejected_count"] += 1
            atomic_rejection_reasons.append(f"{pair_id}:conditional_cash_insufficient")
            continue
        runner.engine.pending_orders.add_orders_atomic(pair_payloads)
        diagnostics["atomic_replacement_registered_count"] += 1
    diagnostics["atomic_replacement_rejection_reasons"] = "|".join(
        atomic_rejection_reasons
    )
    diagnostics["cash_reservation_count"] = len(cash_ledger.snapshot())
    diagnostics["cash_reserved_total"] = cash_ledger.reserved_total
    diagnostics["cash_available_after_reservations"] = cash_ledger.available()
    diagnostics["cash_reservation_contract"] = "cash_reservation_ledger_v1"
    return diagnostics


def is_monthly_normal_buy(*, side: str, order_reason: str, rebalance_frequency: str) -> bool:
    """Return whether a buy belongs to the persistent monthly plan window."""
    return (
        str(side).strip().lower() == "buy"
        and str(rebalance_frequency).strip().lower() == "monthly"
        and str(order_reason).strip().lower() in {"normal_buy", "confirmed_entry_buy"}
    )
