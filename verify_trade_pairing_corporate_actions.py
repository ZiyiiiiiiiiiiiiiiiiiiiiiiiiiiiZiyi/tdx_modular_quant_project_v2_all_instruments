"""Golden test for trade total return with cash and stock dividends."""
import pandas as pd

from functions.execution.trade_pairing import build_trade_pairing_ledgers


orders = pd.DataFrame(
    [
        {
            "symbol": "600001",
            "trade_date": "2025-01-02",
            "side": "buy",
            "executed_shares": 100,
            "price": 10.0,
            "total_cost": 0.0,
            "reason": "normal_buy",
            "order_id": "b1",
            "decision_id": "d1",
            "execution_status": "filled",
        },
        {
            "symbol": "600001",
            "trade_date": "2025-01-10",
            "side": "sell",
            "executed_shares": 110,
            "price": 10.0,
            "total_cost": 0.0,
            "reason": "signal_failure_exit",
            "order_id": "s1",
            "decision_id": "d2",
            "execution_status": "filled",
        },
    ]
)
actions = pd.DataFrame(
    [
        {
            "date": "2025-01-06",
            "symbol": "600001",
            "cash_delta": 50.0,
            "stock_dividend_shares": 10.0,
        }
    ]
)
pairs, opens, summary = build_trade_pairing_ledgers(
    orders, corporate_action_ledger=actions
)
row = pairs.iloc[0]
assert opens.empty
assert abs(float(row["realized_pnl_before_corporate_actions"]) - 100.0) < 1e-12
assert abs(float(row["corporate_action_cash_allocated"]) - 50.0) < 1e-12
assert abs(float(row["realized_pnl_amount"]) - 150.0) < 1e-12
assert abs(float(summary["realized_pnl"]) - 150.0) < 1e-12
assert row["total_return_contract"] == "sale_net_proceeds_plus_corporate_action_cash_v1"
print("[PASS] corporate actions reconcile into trade total return")
