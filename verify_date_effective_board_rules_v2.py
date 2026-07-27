"""Date-effective price-limit and pending corporate-action contracts."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.pending_orders import PendingOrderBook
from functions.execution.security_trading_rules import date_effective_price_limit_rule


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main():
    star_ipo = date_effective_price_limit_rule(
        "sh688001",
        trade_date="2025-01-03",
        trading_sessions_since_listing=3,
        security_status="normal",
    )
    check(not star_ipo.has_daily_price_limit, "STAR first five sessions are represented without a fabricated daily limit")
    ordinary = date_effective_price_limit_rule(
        "sz300001",
        trade_date="2025-01-03",
        trading_sessions_since_listing=20,
        security_status="normal",
    )
    check(ordinary.price_limit_ratio == 0.20 and not ordinary.degraded, "mature ChiNext uses explicit 20 percent rule")
    fallback = date_effective_price_limit_rule(
        "sz000001",
        trade_date="2025-01-03",
        security_status="unknown",
    )
    check(fallback.degraded and fallback.rule_state == "degraded_static_fallback", "missing listing/status evidence is disclosed as degraded")

    book = PendingOrderBook()
    order_id = book.add_order(
        {
            "decision_id": "d1",
            "symbol": "sz000001",
            "side": "sell",
            "reason": "qualification_exit",
            "priority": 1,
            "created_date": pd.Timestamp("2025-01-02"),
            "target_shares": 100,
        }
    )
    changed = book.apply_stock_distribution(
        symbol="sz000001", share_ratio=0.5, event_id="evt-1"
    )
    check(changed == 1, "active pending order follows stock distribution")
    row = book.orders.loc[book.orders["order_id"].eq(order_id)].iloc[0]
    check(float(row["target_shares"]) == 150.0 and float(row["remaining_shares"]) == 150.0, "target and remaining quantities adjust together")
    repeated = book.apply_stock_distribution(
        symbol="sz000001", share_ratio=0.5, event_id="evt-1"
    )
    check(repeated == 0 and float(book.orders.iloc[0]["target_shares"]) == 150.0, "corporate-action event is idempotent")


if __name__ == "__main__":
    main()
