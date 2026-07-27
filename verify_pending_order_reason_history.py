"""Verify persistent sell intents preserve reason evolution."""
import pandas as pd

from functions.decision_council.pending_orders import PendingOrderBook


book = PendingOrderBook()
base = {
    "decision_id": "d1",
    "symbol": "600001",
    "side": "sell",
    "reason": "signal_failure_exit",
    "priority": 3,
    "created_date": pd.Timestamp("2025-01-02"),
    "target_shares": 100,
}
book.upsert_sell_intent(base)
book.upsert_sell_intent(
    {
        **base,
        "decision_id": "d2",
        "reason": "stale_time_exit",
        "created_date": pd.Timestamp("2025-01-03"),
    }
)
row = book.orders.iloc[0]
assert row["origin_reason"] == "signal_failure_exit"
assert row["latest_reason"] == "stale_time_exit"
assert row["highest_priority_reason"] == "stale_time_exit"
assert row["reason"] == "stale_time_exit"
assert row["reason_history"] == "signal_failure_exit|stale_time_exit"

book.upsert_sell_intent(
    {
        **base,
        "decision_id": "d3",
        "reason": "loss_containment_exit",
        "priority": 1,
        "created_date": pd.Timestamp("2025-01-04"),
    }
)
row = book.orders.iloc[0]
assert row["latest_reason"] == "loss_containment_exit"
assert row["highest_priority_reason"] == "loss_containment_exit"
assert row["priority"] == 1
assert row["reason_history"].endswith("loss_containment_exit")
print("[PASS] pending-order origin/latest/highest/history contract")
