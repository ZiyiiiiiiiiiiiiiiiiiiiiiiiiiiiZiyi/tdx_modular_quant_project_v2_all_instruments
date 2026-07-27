"""Terminal open positions remain marked rather than force-liquidated."""
from __future__ import annotations

import pandas as pd

from functions.execution.trade_pairing import build_trade_pairing_ledgers


def main():
    ledger = pd.DataFrame(
        [
            {
                "symbol": "sz000001",
                "trade_date": pd.Timestamp("2025-01-02"),
                "side": "buy",
                "price": 10.0,
                "executed_shares": 100.0,
                "trade_notional": 1_000.0,
                "total_cost": 5.0,
                "execution_status": "filled",
                "order_id": "o1",
                "decision_id": "d1",
                "reason": "normal_buy",
            }
        ]
    )
    prices = pd.DataFrame(
        [{"symbol": "sz000001", "date": "2025-01-31", "trade_close": 11.0}]
    )
    pairs, opens, summary = build_trade_pairing_ledgers(
        ledger, latest_prices=prices, capital_profile="small_capital_branch"
    )
    assert pairs.empty
    assert len(opens) == 1
    assert summary["terminal_position_policy"] == "mark_open_positions_no_forced_liquidation"
    assert summary["open_position_count"] == 1
    assert summary["estimated_terminal_exit_cost"] > 0.0
    assert summary["trade_metric_state"] == "censored"
    print("[PASS] terminal positions are marked, exit-cost stressed and disclosed as censored")


if __name__ == "__main__":
    main()
