"""Verify replacement metadata survives sell upserts and paired buys retry."""
from __future__ import annotations

from functions.decision_council.pending_orders import PendingOrderBook


def main() -> None:
    book = PendingOrderBook()
    book.upsert_sell_intent({
        "decision_id": "normal", "symbol": "sz000001", "reason": "normal_sell",
        "priority": 50, "created_date": "2025-01-02", "target_shares": 100,
    })
    book.upsert_sell_intent({
        "decision_id": "replace", "symbol": "sz000001", "reason": "replacement_opportunity_exit",
        "priority": 10, "created_date": "2025-01-03", "target_shares": 100,
        "replacement_pair_id": "pair_1", "replacement_paired_symbol": "sz000002",
        "replacement_pair_leg": "sell", "replacement_lcb_net_edge": 0.01,
    })
    sell = book.orders.iloc[0]
    assert sell["replacement_pair_id"] == "pair_1"
    assert sell["replacement_pair_leg"] == "sell"

    buy_id = book.add_order({
        "decision_id": "replace", "symbol": "sz000002", "side": "buy",
        "reason": "replacement_opportunity_buy", "priority": 20,
        "created_date": "2025-01-03", "target_shares": 100,
        "replacement_pair_id": "pair_1", "replacement_paired_symbol": "sz000001",
        "replacement_pair_leg": "buy",
    })
    book.settle_day(
        "2025-01-06", blocked_symbols={"sz000002"},
        blocked_reasons={"sz000002": "paired_sell_not_filled"},
    )
    buy = book.orders.set_index("order_id").loc[buy_id]
    assert buy["status"] == "pending"
    assert buy["replacement_pair_status"] == "sell_pending"
    expiring_id = book.add_order({
        "decision_id": "expiring", "symbol": "sz000003", "side": "buy",
        "reason": "replacement_opportunity_buy", "priority": 20,
        "created_date": "2025-01-03", "target_shares": 100,
        "replacement_pair_id": "pair_2", "replacement_paired_symbol": "sz000004",
        "replacement_pair_leg": "buy", "replacement_horizon_days": 1,
    })
    book.settle_day(
        "2025-01-07", blocked_symbols={"sz000003"},
        blocked_reasons={"sz000003": "liquidity_locked"},
    )
    book.settle_day(
        "2025-01-08", blocked_symbols={"sz000003"},
        blocked_reasons={"sz000003": "liquidity_locked"},
    )
    expired = book.orders.set_index("order_id").loc[expiring_id]
    assert expired["status"] == "expired"
    assert expired["expired_reason"] == "replacement_horizon_expired"
    print("[PASS] stale paired buys expire at their registered signal horizon")
    print("[PASS] replacement pending state verification completed")


if __name__ == "__main__":
    main()
