"""Verify unified exits, confirmation, cooldown, and same-symbol precedence."""
from __future__ import annotations

import pandas as pd

from config import get_backtest_capital_profile
from functions.decision_council.decision_arbitration import (
    arbitrate_exit_signals,
    reconcile_same_symbol_orders,
    update_consecutive_confirmation,
)
from functions.decision_council.pending_orders import PendingOrderBook
from functions.decision_council.small_capital_aggressive import (
    scap_control_enabled,
)


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> None:
    _check(
        not scap_control_enabled(exit_stage="E0", control_name="cooldown")
        and scap_control_enabled(exit_stage="E1", control_name="cooldown"),
        "SCAP cooldown authority starts with the E1 lifecycle",
    )
    profile = get_backtest_capital_profile("small_capital_branch")
    _check(
        profile["scap_signal_failure_confirmation_days"] == 3
        and profile["scap_reentry_cooldown_days"] == 10
        and profile["scap_cooldown_override_enabled"] is False,
        "small-capital confirmation and no-override cooldown are explicit",
    )

    arbitration = arbitrate_exit_signals(
        {
            "profit_giveback_exit": True,
            "loss_containment_exit": True,
            "signal_failure_exit": True,
        },
        control_enabled=lambda control: control == "signal_failure_exit",
    )
    _check(
        arbitration.paper_reason == "loss_containment_exit"
        and arbitration.active_reason == "signal_failure_exit"
        and arbitration.conflict_count == 2,
        "unauthorized high-priority exits cannot shadow an authorized exit",
    )

    confirmation_store: dict[str, dict] = {}
    observed = [
        update_consecutive_confirmation(
            confirmation_store,
            symbol="sh600000",
            signal_name="signal_failure_family",
            date=f"2025-01-0{day}",
            triggered=True,
            required_days=3,
        )
        for day in (2, 3, 4)
    ]
    _check(
        observed == [(1, False), (2, False), (3, True)],
        "signal failure requires three consecutive observed decision days",
    )
    reset = update_consecutive_confirmation(
        confirmation_store,
        symbol="sh600000",
        signal_name="signal_failure_family",
        date="2025-01-05",
        triggered=False,
        required_days=3,
    )
    _check(reset == (0, False), "signal recovery resets confirmation")

    orders = pd.DataFrame(
        [
            {
                "decision_id": "d1",
                "decision_date": "2025-01-02",
                "symbol": "sh600000",
                "side": "buy",
                "reason": "normal_buy",
                "priority": 5,
            },
            {
                "decision_id": "d1",
                "decision_date": "2025-01-02",
                "symbol": "sh600000",
                "side": "sell",
                "reason": "signal_failure_exit",
                "priority": 3,
            },
        ]
    )
    reconciled, conflicts = reconcile_same_symbol_orders(orders)
    _check(
        len(reconciled) == 1
        and reconciled.iloc[0]["side"] == "sell"
        and len(conflicts) == 1,
        "same-symbol order arbitration gives sell precedence",
    )

    book = PendingOrderBook()
    book.add_order(
        {
            "decision_id": "d0",
            "symbol": "sh600000",
            "side": "buy",
            "reason": "normal_buy",
            "priority": 5,
            "created_date": "2025-01-02",
            "target_shares": 100,
        }
    )
    book.upsert_sell_intent(
        {
            "decision_id": "d1",
            "symbol": "sh600000",
            "reason": "signal_failure_exit",
            "priority": 3,
            "created_date": "2025-01-03",
            "target_shares": 100,
        }
    )
    prior_buy = book.orders[book.orders["side"].astype(str).eq("buy")].iloc[0]
    _check(
        prior_buy["status"] == "expired"
        and prior_buy["expired_reason"] == "superseded_by_sell_intent",
        "new sell intent cancels an older pending buy for the same symbol",
    )


if __name__ == "__main__":
    main()
