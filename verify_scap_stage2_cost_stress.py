"""Stage-2 checks for SCAP minimum-commission and friction stress."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.scap_cost_stress import build_scap_cost_stress_report


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> None:
    pairs = pd.DataFrame([
        {"entry_order_id": "b1", "sell_order_id": "s1", "entry_shares": 100.0, "realized_pnl_amount": 90.0},
        {"entry_order_id": "b2", "sell_order_id": "s2", "entry_shares": 100.0, "realized_pnl_amount": -60.0},
    ])
    ledger = pd.DataFrame([
        {"order_id": "b1", "side": "buy", "price": 10.0, "executed_shares": 100.0, "execution_status": "filled", "stamp_duty_cost": 0.0, "transfer_fee_cost": 0.01, "slippage_cost": 0.5, "market_impact_cost": 0.1},
        {"order_id": "s1", "side": "sell", "price": 11.0, "executed_shares": 100.0, "execution_status": "filled", "stamp_duty_cost": 0.55, "transfer_fee_cost": 0.011, "slippage_cost": 0.55, "market_impact_cost": 0.1},
        {"order_id": "b2", "side": "buy", "price": 20.0, "executed_shares": 100.0, "execution_status": "filled", "stamp_duty_cost": 0.0, "transfer_fee_cost": 0.02, "slippage_cost": 1.0, "market_impact_cost": 0.2},
        {"order_id": "s2", "side": "sell", "price": 19.5, "executed_shares": 100.0, "execution_status": "filled", "stamp_duty_cost": 0.975, "transfer_fee_cost": 0.0195, "slippage_cost": 0.975, "market_impact_cost": 0.2},
    ])
    report = build_scap_cost_stress_report(pairs, ledger, initial_cash=20_000.0)
    _check(len(report) == 9, "three minimum commissions by three friction multipliers are reported")
    base = report[(report["minimum_commission"] == 0.0) & (report["market_cost_multiplier"] == 1.0)].iloc[0]
    expensive = report[(report["minimum_commission"] == 5.0) & (report["market_cost_multiplier"] == 2.0)].iloc[0]
    _check(int(base["closed_trade_count"]) == 2, "all closed trades are repriced")
    _check(float(expensive["stressed_total_cost"]) > float(base["stressed_total_cost"]), "higher broker and market costs increase total cost")
    _check(float(expensive["stressed_net_pnl_amount"]) < float(base["stressed_net_pnl_amount"]), "higher costs reduce net profit")
    _check("profit_factor_after_cost" in report.columns, "profit factor is recomputed after scenario costs")
    _check("cost_to_initial_capital" in report.columns, "small-account capital cost ratio is explicit")
    empty_report = build_scap_cost_stress_report(
        pd.DataFrame(columns=pairs.columns),
        pd.DataFrame(),
        initial_cash=20_000.0,
    )
    _check(empty_report.empty, "a no-closed-trade smoke run produces an empty report instead of failing")
    _check(
        list(empty_report.columns) == list(report.columns),
        "the no-trade report preserves the production output schema",
    )


if __name__ == "__main__":
    main()
