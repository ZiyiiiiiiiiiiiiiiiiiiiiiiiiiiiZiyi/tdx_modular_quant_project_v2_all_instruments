"""Product checks for transaction-cost and capacity stress."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.cost_capacity_audit import build_cost_capacity_stress_reports


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def fixture(count=12):
    pairs, orders = [], []
    for index in range(count):
        buy_id, sell_id = f"b{index}", f"s{index}"
        shares, buy_price, sell_price, fee = 100, 10.0, 10.12, 2.5
        gross = shares * (sell_price - buy_price)
        pairs.append({"trade_id": f"t{index}", "entry_order_id": buy_id, "sell_order_id": sell_id,
                      "entry_shares": shares, "realized_pnl_amount": gross - 2 * fee})
        orders.extend([
            {"order_id": buy_id, "side": "buy", "price": buy_price, "executed_shares": shares,
             "total_cost": fee, "market_amount": 5_000_000, "execution_status": "filled"},
            {"order_id": sell_id, "side": "sell", "price": sell_price, "executed_shares": shares,
             "total_cost": fee, "market_amount": 5_000_000, "execution_status": "filled"},
        ])
    return pd.DataFrame(pairs), pd.DataFrame(orders)


def main():
    pairs, ledger = fixture()
    before = pairs.copy(deep=True)
    reports = build_cost_capacity_stress_reports(
        pairs, ledger, cost_multipliers=(0, 1, 3), capital_scales=(1, 10, 100),
        impact_sqrt_coefficient=.001, impact_max_rate=.02, maximum_participation_rate=.01,
    )
    summary = reports["governance_failure_lab_cost_capacity_summary"].iloc[0]
    scenarios = reports["governance_failure_lab_cost_capacity_scenarios"]
    reconstructed = reports["governance_failure_lab_cost_capacity_trade_reconstruction"]
    check(summary["evidence_status"] == "cost_capacity_stress_pass", "profitable liquid base case passes")
    check(abs(summary["observed_net_pnl_reconstructed"] - summary["ledger_realized_pnl"]) < 1e-9, "gross minus observed costs reconciles to ledger PnL")
    check((scenarios[scenarios["cost_multiplier"].eq(3)]["stressed_net_pnl_amount"] < 0).all(), "three-times observed costs destroy the planted thin edge")
    check(scenarios[scenarios["capital_scale"].eq(100)]["participation_limit_breached"].all(), "large scale breaches the stated participation limit")
    check(reconstructed["maximum_leg_participation_rate"].notna().all(), "every reconstructed trade retains market participation")
    check(pairs.equals(before), "cost audit does not mutate trade pairs")

    short_pairs, short_ledger = fixture(2)
    short = build_cost_capacity_stress_reports(
        short_pairs, short_ledger, impact_sqrt_coefficient=.001, impact_max_rate=.02,
        minimum_closed_trades=10,
    )["governance_failure_lab_cost_capacity_summary"].iloc[0]
    check(short["evidence_status"] == "insufficient_closed_trades", "short trade history fails closed")
    print("[PASS] cost and capacity product verification completed")


if __name__ == "__main__":
    main()
