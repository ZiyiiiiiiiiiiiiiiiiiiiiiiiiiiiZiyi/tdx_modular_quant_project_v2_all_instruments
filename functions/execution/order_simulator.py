# -*- coding: utf-8 -*-
import pandas as pd

from functions.execution.cost_model import estimate_trade_costs
from functions.execution.execution_rules import apply_a_share_constraints


SIMULATED_ORDER_COLUMNS = [
    "symbol",
    "trade_date",
    "side",
    "target_shares",
    "price",
    "constraint_blocked",
    "execution_status",
    "executed_shares",
    "remaining_shares",
]


def simulate_order_book(order_df):
    constrained = apply_a_share_constraints(order_df)
    constrained["execution_status"] = constrained["constraint_blocked"].map(
        {True: "pending", False: "filled"}
    )
    constrained["executed_shares"] = constrained["target_shares"].where(
        ~constrained["constraint_blocked"],
        0.0,
    )
    simulated = estimate_trade_costs(constrained, shares_col="executed_shares")
    simulated["remaining_shares"] = simulated["target_shares"] - simulated["executed_shares"]
    return simulated


def build_delayed_order_queue(simulated_orders):
    delayed = simulated_orders[simulated_orders["execution_status"] != "filled"].copy()
    if delayed.empty:
        delayed["delay_reason"] = pd.Series(dtype=object)
        delayed["delay_days"] = pd.Series(dtype=float)
        return delayed

    delayed["delay_reason"] = delayed.apply(_infer_delay_reason, axis=1)
    delayed["delay_days"] = 1
    return delayed


def _infer_delay_reason(row):
    if str(row.get("execution_status", "")) == "pending_cash":
        return "cash_unavailable_after_blocked_sale"
    if bool(row.get("t_plus_one_blocked", False)):
        return "t_plus_one"
    if bool(row.get("price_limit_blocked", False)):
        return "price_limit"
    if bool(row.get("suspension_blocked", False)):
        return "suspension"
    if not bool(row.get("lot_size_valid", True)):
        return "lot_size"
    return "unknown"
