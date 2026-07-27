"""Standalone governance execution and account integrity checks."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.runtime_integrity_audit import build_runtime_integrity_audit


def main() -> int:
    execution = pd.DataFrame([
        {
            "order_id": "o1", "signal_date": "2024-01-02", "trade_date": "2024-01-03",
            "decision_timestamp": "2024-01-02 15:00:00", "next_trading_day": "2024-01-03",
            "execution_price_basis": "next_available_trading_day_open_nominal",
            "execution_status": "filled", "target_shares": 100,
            "executed_shares": 100, "remaining_shares": 0,
        }
    ])
    account = pd.DataFrame([{"reconciliation_error": 0.0}])
    daily = pd.DataFrame(
        [
            {
                "date": "2024-01-03",
                "actual_exposure": 0.20,
                "effective_target_exposure_cap": 0.50,
            }
        ]
    )
    audit = build_runtime_integrity_audit(
        execution_ledger=execution,
        account_audit=account,
        daily_result=daily,
    )
    assert audit["passed"].all(), audit.to_dict("records")
    broken = execution.copy()
    broken.loc[0, "trade_date"] = "2024-01-02"
    failed = build_runtime_integrity_audit(
        execution_ledger=broken,
        account_audit=account,
        daily_result=daily,
    )
    assert not bool(failed.loc[failed["check"].eq("signal_before_execution"), "passed"].iloc[0])
    print("[PASS] execution status, timing, shares, and account reconciliation are audited")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
