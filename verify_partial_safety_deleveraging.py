"""Product verification for partial safety deleveraging lot semantics."""
from types import SimpleNamespace

import pandas as pd

from functions.decision_council.execution_runtime import Position, register_orders


class PendingOrders:
    def __init__(self):
        self.payloads = []

    def upsert_sell_intent(self, payload):
        self.payloads.append(payload)

    def add_order(self, payload):
        self.payloads.append(payload)


class Calendar:
    @staticmethod
    def next_session(date):
        return pd.Timestamp(date) + pd.offsets.BDay(1)

    @staticmethod
    def previous_session(date):
        return pd.Timestamp(date) - pd.offsets.BDay(1)


class PriceLedger:
    @staticmethod
    def mark(symbol, *, as_of):
        return None


def runner_with(position_shares):
    pending = PendingOrders()
    runner = SimpleNamespace(
        _retail_lot_adapter_enabled=False,
        strategy_logic_version="mainline_v3_cabinet_native",
        trading_calendar=Calendar(),
        price_ledger=PriceLedger(),
        cash=20_000.0,
        positions={"sh600000": Position(float(position_shares), pd.Timestamp("2024-01-02"))},
        engine=SimpleNamespace(pending_orders=pending),
        _retail_cash_required=lambda **kwargs: 1_005.0,
        _record_retail_execution_diagnostic=lambda **kwargs: None,
    )
    return runner, pending


def order(reason, target_weight, delta_weight):
    return pd.DataFrame([{
        "decision_id": f"{reason}-1",
        "decision_date": pd.Timestamp("2024-01-10"),
        "execution_date": pd.Timestamp("2024-01-11"),
        "symbol": "sh600000",
        "side": "sell",
        "reason": reason,
        "priority": 0,
        "current_weight": 0.50,
        "target_weight": target_weight,
        "delta_weight": delta_weight,
    }])


def main():
    daily = pd.DataFrame([{"symbol": "sh600000", "close_nominal": 10.0}])

    runner, pending = runner_with(1_000)
    register_orders(runner, order("safety_deleveraging", 0.40, -0.10), daily, 20_000.0)
    assert len(pending.payloads) == 1
    assert pending.payloads[0]["target_shares"] == 200.0
    print("[PASS] safety deleveraging preserves a two-lot partial reduction")

    runner, pending = runner_with(1_000)
    register_orders(runner, order("hard_stop_exit", 0.0, -0.10), daily, 20_000.0)
    assert pending.payloads[0]["target_shares"] == 1_000.0
    print("[PASS] explicit hard exit still liquidates the full inventory")

    runner, pending = runner_with(1_000)
    register_orders(runner, order("safety_deleveraging", 0.0, -0.10), daily, 20_000.0)
    assert pending.payloads[0]["target_shares"] == 1_000.0
    print("[PASS] zero target remains an explicit full liquidation")


if __name__ == "__main__":
    main()
