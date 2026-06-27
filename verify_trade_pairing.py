# -*- coding: utf-8 -*-
import pandas as pd

from config import backtest_profile_suffix, get_backtest_capital_profile
from functions.execution.trade_pairing import build_trade_pairing_ledgers


def verify_trade_pairing():
    failures = []
    print("=== Verify trade pairing and capital profile plumbing ===")

    baseline = get_backtest_capital_profile("institutional_1m")
    retail = get_backtest_capital_profile("retail_20k")
    if float(baseline["initial_cash"]) != 1_000_000.0:
        failures.append("institutional_1m initial cash drifted")
        print("[FAIL] institutional_1m initial cash drifted")
    else:
        print("[PASS] institutional_1m initial cash preserved")

    if float(retail["initial_cash"]) != 20_000.0 or int(retail["max_positions"]) != 5:
        failures.append("retail_20k profile parameters are incorrect")
        print("[FAIL] retail_20k profile parameters are incorrect")
    else:
        print("[PASS] retail_20k profile parameters correct")

    if backtest_profile_suffix("institutional_1m") != "":
        failures.append("default profile should not add a file suffix")
        print("[FAIL] default profile should not add a file suffix")
    else:
        print("[PASS] default profile file suffix is empty")

    if backtest_profile_suffix("retail_20k") != "__retail_20k":
        failures.append("retail profile suffix is incorrect")
        print("[FAIL] retail profile suffix is incorrect")
    else:
        print("[PASS] retail profile suffix is correct")

    orders = pd.DataFrame(
        [
            {
                "symbol": "sh600000",
                "trade_date": "2024-01-02",
                "side": "buy",
                "price": 10.0,
                "executed_shares": 100.0,
                "total_cost": 1.0,
                "execution_status": "filled",
            },
            {
                "symbol": "sh600000",
                "trade_date": "2024-01-03",
                "side": "buy",
                "price": 20.0,
                "executed_shares": 100.0,
                "total_cost": 2.0,
                "execution_status": "filled",
            },
            {
                "symbol": "sh600000",
                "trade_date": "2024-01-05",
                "side": "sell",
                "price": 18.0,
                "executed_shares": 100.0,
                "total_cost": 1.8,
                "execution_status": "filled",
            },
            {
                "symbol": "sz000001",
                "trade_date": "2024-01-03",
                "side": "buy",
                "price": 20.0,
                "executed_shares": 100.0,
                "total_cost": 2.0,
                "execution_status": "filled",
            },
        ]
    )
    prices = pd.DataFrame(
        [
            {"date": "2024-01-05", "symbol": "sz000001", "trade_close": 21.5},
            {"date": "2024-01-05", "symbol": "sh600000", "trade_close": 19.0},
        ]
    )
    trade_pairs, open_positions, summary = build_trade_pairing_ledgers(
        orders,
        prices,
        capital_profile="retail_20k",
    )

    if len(trade_pairs) != 1:
        failures.append(f"expected 1 closed trade, got {len(trade_pairs)}")
        print(f"[FAIL] expected 1 closed trade, got {len(trade_pairs)}")
    else:
        print("[PASS] one closed trade produced")

    if len(open_positions) != 2:
        failures.append(f"expected 2 open positions, got {len(open_positions)}")
        print(f"[FAIL] expected 2 open positions, got {len(open_positions)}")
    else:
        print("[PASS] open positions produced separately")

    realized = float(trade_pairs.iloc[0]["realized_pnl_amount"]) if not trade_pairs.empty else 0.0
    expected_realized = 100.0 * (18.0 - 0.018 - ((100.0 * 10.0 + 1.0 + 100.0 * 20.0 + 2.0) / 200.0))
    if abs(realized - expected_realized) > 1e-9:
        failures.append(f"weighted-cost realized pnl mismatch: {realized} != {expected_realized}")
        print(f"[FAIL] weighted-cost realized pnl mismatch: {realized} != {expected_realized}")
    else:
        print("[PASS] weighted-cost realized pnl is correct")

    closed = trade_pairs.iloc[0]
    if float(closed["entry_shares"]) != 100.0 or float(closed["exit_shares"]) != 100.0:
        failures.append("partial sell should produce one trade for the sold shares only")
        print("[FAIL] partial sell should produce one trade for the sold shares only")
    else:
        print("[PASS] partial sell produces one closed trade for sold shares")

    sh_open = open_positions[open_positions["symbol"].astype(str).eq("sh600000")]
    if sh_open.empty or float(sh_open.iloc[0]["shares"]) != 100.0:
        failures.append("remaining shares after partial sell should stay open")
        print("[FAIL] remaining shares after partial sell should stay open")
    else:
        print("[PASS] remaining shares stay in open positions")

    if float(summary["trade_win_rate"]) != 1.0:
        failures.append("trade win rate should be 1.0 for the sample ledger")
        print("[FAIL] trade win rate should be 1.0 for the sample ledger")
    else:
        print("[PASS] trade win rate computed correctly")

    if float(summary["unrealized_pnl_amount"]) <= 0.0:
        failures.append("expected positive unrealized pnl for the remaining open position")
        print("[FAIL] expected positive unrealized pnl for the remaining open position")
    else:
        print("[PASS] unrealized pnl computed correctly")

    print()
    if failures:
        print("Trade pairing verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Trade pairing verification passed.")


if __name__ == "__main__":
    verify_trade_pairing()
