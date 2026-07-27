"""Pending-order atomicity and fill-id idempotency checks."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.pending_orders import PendingOrderBook


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def payload(symbol, side, leg):
    return {
        "decision_id": "d1",
        "symbol": symbol,
        "side": side,
        "reason": f"replacement_opportunity_{side}",
        "priority": 1,
        "created_date": pd.Timestamp("2025-01-02"),
        "target_shares": 100,
        "replacement_pair_id": "pair-1",
        "replacement_pair_leg": leg,
        "action_plan_id": "d1|action_plan",
        "action_proposal_id": f"d1|{symbol}|{leg}",
        "action_plan_selected": True,
        "action_plan_contract": "scap_v3_lean_contracts_v1",
        "cash_reservation_id": f"d1|{symbol}|reservation",
    }


def main():
    book = PendingOrderBook()
    sell = payload("sz000001", "sell", "sell")
    buy = payload("sz000002", "buy", "buy")
    ids = book.add_orders_atomic([sell, buy])
    check(len(ids) == 2 and len(book.orders) == 2, "complete replacement pair commits atomically")
    repeated = book.add_orders_atomic([sell, buy])
    check(set(repeated) == set(ids) and len(book.orders) == 2, "repeated registration is idempotent")
    check(
        book.orders["action_plan_id"].eq("d1|action_plan").all()
        and book.orders["action_proposal_id"].astype(str).str.len().gt(0).all()
        and book.orders["cash_reservation_id"].astype(str).str.len().gt(0).all(),
        "pending rows preserve populated plan/proposal/reservation lineage",
    )

    incomplete = PendingOrderBook()
    try:
        incomplete.add_orders_atomic([sell])
    except ValueError:
        pass
    else:
        raise AssertionError("incomplete pair must fail")
    check(incomplete.orders.empty, "incomplete replacement pair commits nothing")

    order_id = ids[0]
    event = {"shares": 40.0, "fill_id": "fill-1"}
    book.settle_day(pd.Timestamp("2025-01-03"), fills={order_id: event})
    remaining = float(book.orders.loc[book.orders["order_id"].eq(order_id), "remaining_shares"].iloc[0])
    check(remaining == 60.0, "first partial fill updates remaining shares")
    book.settle_day(pd.Timestamp("2025-01-03"), fills={order_id: event})
    repeated_remaining = float(book.orders.loc[book.orders["order_id"].eq(order_id), "remaining_shares"].iloc[0])
    check(repeated_remaining == 60.0, "replayed fill id does not execute twice")
    status = str(book.orders.loc[book.orders["order_id"].eq(order_id), "status"].iloc[0])
    check(status == "pending", "partial sell remains pending")


if __name__ == "__main__":
    main()
