# -*- coding: utf-8 -*-
import pandas as pd

from functions.execution.cost_model import estimate_trade_costs
from functions.execution.execution_rules import (
    REQUIRED_ORDER_COLUMNS,
    apply_a_share_constraints,
    normalize_order_frame,
)


def _check_columns(frame, required_columns, label, failures):
    missing = sorted(set(required_columns) - set(frame.columns))
    if missing:
        failures.append(f"{label} missing columns: {missing}")
        print(f"[FAIL] {label}: missing columns {missing}")
    else:
        print(f"[PASS] {label}: required columns present")


def verify_execution_rules():
    failures: list[str] = []
    print("=== Verify execution rules skeleton ===")

    orders = pd.DataFrame(
        [
            {
                "symbol": "sh600000",
                "trade_date": "2024-06-28",
                "side": "buy",
                "target_shares": 100,
                "price": 10.0,
                "same_day_sell_blocked": False,
                "price_limit_blocked_flag": False,
                "suspension_blocked_flag": False,
            },
            {
                "symbol": "sz000001",
                "trade_date": "2024-06-28",
                "side": "sell",
                "target_shares": 150,
                "price": 12.0,
                "same_day_sell_blocked": True,
                "price_limit_blocked_flag": False,
                "suspension_blocked_flag": True,
            },
        ]
    )

    normalized = normalize_order_frame(orders)
    _check_columns(normalized, REQUIRED_ORDER_COLUMNS, "normalized orders", failures)

    constrained = apply_a_share_constraints(orders)
    for col in [
        "lot_size_valid",
        "t_plus_one_blocked",
        "price_limit_blocked",
        "suspension_blocked",
        "constraint_blocked",
    ]:
        if col not in constrained.columns:
            failures.append(f"constraint column missing: {col}")
            print(f"[FAIL] constraint column missing: {col}")
    if not any("constraint column missing" in item for item in failures):
        print("[PASS] constraint columns generated")

    if bool(constrained.loc[1, "constraint_blocked"]) is not True:
        failures.append("expected blocked sell order was not blocked")
        print("[FAIL] expected blocked sell order was not blocked")
    else:
        print("[PASS] blocked order correctly flagged")

    costs = estimate_trade_costs(orders)
    for col in [
        "trade_notional",
        "commission_cost",
        "slippage_cost",
        "stamp_duty_cost",
        "total_cost",
    ]:
        if col not in costs.columns:
            failures.append(f"cost column missing: {col}")
            print(f"[FAIL] cost column missing: {col}")
    if not any("cost column missing" in item for item in failures):
        print("[PASS] cost columns generated")

    if float(costs.loc[0, "stamp_duty_cost"]) != 0.0:
        failures.append("buy order should not have stamp duty cost")
        print("[FAIL] buy order should not have stamp duty cost")
    else:
        print("[PASS] buy order stamp duty handling correct")

    if float(costs.loc[1, "stamp_duty_cost"]) <= 0.0:
        failures.append("sell order should have positive stamp duty cost")
        print("[FAIL] sell order should have positive stamp duty cost")
    else:
        print("[PASS] sell order stamp duty handling correct")

    print()
    if failures:
        print("Execution rules verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Execution rules verification passed.")


if __name__ == "__main__":
    verify_execution_rules()
