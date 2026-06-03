# -*- coding: utf-8 -*-
import tempfile
from pathlib import Path

import pandas as pd

from functions.execution.liquidity_lock_handler import (
    LIQUIDITY_LOCK_COLUMNS,
    build_liquidity_lock_report,
    save_liquidity_lock_report,
)
from functions.execution.order_simulator import (
    SIMULATED_ORDER_COLUMNS,
    build_delayed_order_queue,
    simulate_order_book,
)


def _check_columns(frame, required_columns, label, failures):
    missing = sorted(set(required_columns) - set(frame.columns))
    if missing:
        failures.append(f"{label} missing columns: {missing}")
        print(f"[FAIL] {label}: missing columns {missing}")
    else:
        print(f"[PASS] {label}: required columns present")


def verify_order_simulator():
    failures: list[str] = []
    print("=== Verify order simulator skeleton ===")

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
                "target_shares": 200,
                "price": 12.0,
                "same_day_sell_blocked": False,
                "price_limit_blocked_flag": True,
                "suspension_blocked_flag": False,
            },
        ]
    )

    simulated = simulate_order_book(orders)
    _check_columns(simulated, SIMULATED_ORDER_COLUMNS, "simulated orders", failures)

    if simulated.loc[0, "execution_status"] != "filled":
        failures.append("expected first order to be filled")
        print("[FAIL] expected first order to be filled")
    else:
        print("[PASS] filled order status correct")

    if simulated.loc[1, "execution_status"] != "pending":
        failures.append("expected second order to be pending")
        print("[FAIL] expected second order to be pending")
    else:
        print("[PASS] pending order status correct")

    if float(simulated.loc[1, "trade_notional"]) != 0.0 or float(simulated.loc[1, "total_cost"]) != 0.0:
        failures.append("pending order should not produce turnover or transaction cost")
        print("[FAIL] pending order produced turnover or transaction cost")
    else:
        print("[PASS] pending order is not charged transaction costs")

    if float(simulated.loc[0, "trade_notional"]) <= 0.0 or float(simulated.loc[0, "total_cost"]) <= 0.0:
        failures.append("filled order should produce turnover and transaction cost")
        print("[FAIL] filled order missing turnover or transaction cost")
    else:
        print("[PASS] filled order is charged transaction costs")

    delayed = build_delayed_order_queue(simulated)
    if delayed.empty:
        failures.append("expected delayed queue to contain one order")
        print("[FAIL] expected delayed queue to contain one order")
    else:
        print(f"[PASS] delayed queue size: {len(delayed)}")

    report = build_liquidity_lock_report(delayed, max_lock_days=1)
    _check_columns(report, LIQUIDITY_LOCK_COLUMNS, "liquidity lock report", failures)

    if report.empty or bool(report.loc[0, "forced_exit_triggered"]) is not True:
        failures.append("expected forced exit to trigger at max_lock_days=1")
        print("[FAIL] expected forced exit to trigger at max_lock_days=1")
    else:
        print("[PASS] liquidity lock forced-exit flag correct")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        report_file = save_liquidity_lock_report(report, tmp_path / "lock_report.csv")
        if not report_file.exists():
            failures.append(f"liquidity lock report missing after save: {report_file}")
            print(f"[FAIL] liquidity lock report missing after save: {report_file}")
        else:
            print(f"[PASS] liquidity lock report saved: {report_file}")

    print()
    if failures:
        print("Order simulator verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Order simulator verification passed.")


if __name__ == "__main__":
    verify_order_simulator()
