# -*- coding: utf-8 -*-
import pandas as pd

from functions.execution.cost_model import estimate_trade_costs
from functions.execution.execution_rules import (
    REQUIRED_ORDER_COLUMNS,
    apply_a_share_constraints,
    a_share_price_limit_ratio,
    classify_daily_limit_feasibility,
    normalize_order_frame,
    rounded_price_limit,
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
        "transfer_fee_cost",
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

    if a_share_price_limit_ratio("sh600000") != 0.10:
        failures.append("main-board price limit should be 10%")
    if a_share_price_limit_ratio("sz300001") != 0.20:
        failures.append("ChiNext price limit should be 20%")
    if a_share_price_limit_ratio("bj430001") != 0.30:
        failures.append("BSE price limit should be 30%")
    if a_share_price_limit_ratio("sh600000", is_st=True) != 0.05:
        failures.append("ST price limit should be 5%")
    if rounded_price_limit(10.03, 0.10, "up") != 11.03:
        failures.append("price-limit decimal rounding mismatch")
    if not any("price limit should" in item or "rounding mismatch" in item for item in failures):
        print("[PASS] board/ST price-limit ratios and rounding correct")

    blocked = classify_daily_limit_feasibility(
        side="buy", open_price=11.0, high_price=11.0, low_price=11.0, close_price=11.0,
        limit_price=11.0, amount=1.0, rolling_amount=100.0,
    )
    uncertain = classify_daily_limit_feasibility(
        side="sell", open_price=9.0, high_price=9.1, low_price=9.0, close_price=9.0,
        limit_price=9.0, amount=20.0, rolling_amount=100.0,
    )
    if blocked != "blocked_limit_buy" or uncertain != "high_uncertainty_limit_event":
        failures.append("daily limit feasibility classification mismatch")
    else:
        print("[PASS] one-price board and high-uncertainty classification correct")

    print()
    if failures:
        print("Execution rules verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Execution rules verification passed.")


if __name__ == "__main__":
    verify_execution_rules()
