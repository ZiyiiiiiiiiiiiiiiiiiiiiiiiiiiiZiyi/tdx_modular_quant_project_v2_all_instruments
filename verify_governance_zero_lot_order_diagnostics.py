"""Product verification for explicit sub-lot order diagnostics."""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from functions.decision_council.execution_runtime import register_orders


class _PendingOrders:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def upsert_sell_intent(self, payload: dict) -> None:
        self.payloads.append(payload)

    def add_order(self, payload: dict) -> None:
        self.payloads.append(payload)


class _Calendar:
    @staticmethod
    def next_session(date):
        return pd.Timestamp(date) + pd.offsets.BDay(1)

    @staticmethod
    def previous_session(date):
        return pd.Timestamp(date) - pd.offsets.BDay(1)


class _PriceLedger:
    @staticmethod
    def mark(symbol, *, as_of):
        return None


def main() -> None:
    records: list[dict] = []
    pending = _PendingOrders()
    runner = SimpleNamespace(
        _retail_lot_adapter_enabled=False,
        strategy_logic_version="mainline_v3_reliability_weighted",
        trading_calendar=_Calendar(),
        price_ledger=_PriceLedger(),
        cash=20_000.0,
        engine=SimpleNamespace(pending_orders=pending),
        _retail_cash_required=lambda **kwargs: 1_005.0,
        _record_retail_execution_diagnostic=lambda **kwargs: records.append(kwargs),
    )
    orders = pd.DataFrame(
        [{
            "decision_id": "zero_lot_sell",
            "decision_date": pd.Timestamp("2024-10-11"),
            "execution_date": pd.Timestamp("2024-10-14"),
            "symbol": "sh600999",
            "side": "sell",
            "reason": "safety_deleveraging",
            "priority": 0,
            "current_weight": 0.094,
            "target_weight": 0.091,
            "delta_weight": -0.003,
        }]
    )
    daily = pd.DataFrame([{"symbol": "sh600999", "close_nominal": 20.0}])
    diagnostics = register_orders(runner, orders, daily, nominal_nav=20_000.0)

    assert diagnostics["zero_lot_order_count"] == 1
    assert diagnostics["zero_lot_sell_order_count"] == 1
    assert diagnostics["zero_lot_buy_order_count"] == 0
    assert diagnostics["retail_blocked_count"] == 1
    assert not pending.payloads, "an infeasible zero-share intent must not enter pending orders"
    assert len(records) == 1
    assert records[0]["retail_action"] == "blocked_zero_lot"
    assert records[0]["retail_block_reason"] == "sell_weight_change_below_one_lot"
    assert records[0]["target_shares"] == 0.0
    print("[PASS] sub-lot sell is explicitly counted and audited")
    print("[PASS] sub-lot sell does not silently enter the pending-order book")


if __name__ == "__main__":
    main()
