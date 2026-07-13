"""Order registration and execution runtime for governance backtests."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from config import MIN_LOT_SIZE
from functions.execution.cost_model import estimate_trade_costs
from functions.execution.order_simulator import simulate_order_book


@dataclass
class Position:
    shares: float
    acquired_date: pd.Timestamp


def execute_pending(runner, date, daily):
    active = runner.engine.pending_orders.orders
    active = active[
        active["status"].isin(["pending", "pending_locked"])
        & (pd.to_datetime(active["created_date"], errors="coerce") < pd.Timestamp(date))
    ].copy()
    if active.empty:
        return
    market = daily.set_index("symbol", drop=False)
    rows = []
    blocked_symbols = set()
    fill_map = {}
    for _, order in active.sort_values(["priority", "created_date"]).iterrows():
        symbol = str(order["symbol"])
        if symbol not in market.index:
            blocked_symbols.add(symbol)
            continue
        quote = market.loc[symbol]
        price = float(quote["open_nominal"])
        requested = float(order["remaining_shares"])
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
            "price": price,
            "market_amount": float(pd.to_numeric(pd.Series([quote.get("amount", 0.0)]), errors="coerce").fillna(0.0).iloc[0]),
            "same_day_sell_blocked": bool(
                str(order["side"]) == "sell"
                and symbol in runner.positions
                and runner.positions[symbol].acquired_date >= pd.Timestamp(date)
            ),
            "price_limit_blocked_flag": bool(
                quote["rough_limit_up"] if str(order["side"]) == "buy" else quote["rough_limit_down"]
            ),
            "suspension_blocked_flag": not bool(quote["is_trading"]),
            "order_id": order["order_id"],
            "decision_id": order["decision_id"],
            "reason": order["reason"],
            "position_state": order.get("position_state", ""),
            "position_exit_reason": order.get("position_exit_reason", ""),
            "add_layer": order.get("add_layer", pd.NA),
            "add_allowed": order.get("add_allowed", False),
            "add_block_reason": order.get("add_block_reason", ""),
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
        }
        rows.append(row)
    if not rows:
        runner.engine.settle_pending_orders(date, blocked_symbols=blocked_symbols)
        return
    simulated = simulate_order_book(pd.DataFrame(rows))
    for _, fill in simulated.iterrows():
        symbol = str(fill["symbol"])
        order_id = str(fill["order_id"])
        if fill["execution_status"] != "filled":
            blocked_symbols.add(symbol)
            continue
        shares = float(fill["executed_shares"])
        notional = float(fill["trade_notional"])
        cost = float(fill["total_cost"])
        if str(fill["side"]) == "buy":
            affordable = max(runner.cash - cost, 0.0)
            shares = min(shares, float(int(affordable // float(fill["price"]) // MIN_LOT_SIZE) * MIN_LOT_SIZE))
            if shares <= 0:
                continue
            recalculated = estimate_trade_costs(pd.DataFrame([{**fill.to_dict(), "target_shares": shares}]))
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
                runner._register_position_cooldown(symbol, date=date, reason=str(fill.get("reason", "")))
            else:
                runner.positions[symbol] = Position(remaining, current.acquired_date)
        fill_map[order_id] = shares
        record = fill.to_dict()
        record.update({"executed_shares": shares, "trade_notional": notional, "total_cost": cost, "order_id": order_id})
        runner.execution_rows.append(record)
        if str(fill["side"]) == "sell" and str(fill.get("reason")) == "alpha_collapse_consensus":
            runner._pending_alpha_collapse_exits.append(
                {
                    "decision_id": fill.get("decision_id"),
                    "symbol": symbol,
                    "exit_date": pd.Timestamp(date),
                    "exit_price": float(fill["price"]),
                }
            )
    runner.engine.settle_pending_orders(date, fills=fill_map, blocked_symbols=blocked_symbols)

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
    }
    if orders.empty:
        return diagnostics
    if runner._retail_lot_adapter_enabled:
        orders = runner._sort_retail_orders(orders)
    prices = daily.set_index("symbol")["close_nominal"]
    reserved_cash = 0.0
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
                available_cash=max(float(runner.cash) - reserved_cash, 0.0),
                retail_action="blocked_no_price",
                retail_block_reason="missing_price",
            )
            diagnostics["retail_no_price_count"] += 1
            diagnostics["retail_blocked_count"] += 1
            continue
        shares = abs(float(order["delta_weight"])) * float(nominal_nav) / order_price
        shares = float(int(shares // MIN_LOT_SIZE) * MIN_LOT_SIZE)
        strategy_target_notional = abs(float(order["delta_weight"])) * float(nominal_nav)
        retail_action = "unchanged"
        retail_block_reason = ""
        one_lot_cost = float(order_price) * float(MIN_LOT_SIZE)
        one_lot_cash_required = runner._retail_cash_required(
            side=str(order["side"]),
            price=order_price,
            shares=float(MIN_LOT_SIZE),
        )
        if runner._retail_lot_adapter_enabled and str(order["side"]) == "buy":
            diagnostics["retail_order_count"] += 1
            shares, retail_action, retail_block_reason = runner._adapt_retail_buy_order(
                order=order,
                strategy_target_notional=strategy_target_notional,
                order_price=order_price,
                nominal_nav=nominal_nav,
                reserved_cash=reserved_cash,
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
                available_cash=max(float(runner.cash) - reserved_cash, 0.0),
                retail_action=retail_action,
                retail_block_reason=retail_block_reason,
            )
        if shares <= 0:
            continue
        if runner._retail_lot_adapter_enabled and str(order["side"]) == "buy":
            reserved_cash += runner._retail_cash_required(
                side=str(order["side"]),
                price=order_price,
                shares=shares,
            )
        payload = {
            "decision_id": order["decision_id"],
            "symbol": symbol,
            "side": order["side"],
            "reason": order["reason"],
            "priority": int(order["priority"]),
            "created_date": decision_date,
            "scheduled_execution_date": actual_execution_date,
            "target_shares": shares,
            "position_state": order.get("position_state", ""),
            "position_exit_reason": order.get("position_exit_reason", ""),
            "add_layer": order.get("add_layer", pd.NA),
            "add_allowed": order.get("add_allowed", False),
            "add_block_reason": order.get("add_block_reason", ""),
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
        }
        if order["side"] == "sell":
            runner.engine.pending_orders.upsert_sell_intent(payload)
        else:
            runner.engine.pending_orders.add_order(payload)
    return diagnostics

