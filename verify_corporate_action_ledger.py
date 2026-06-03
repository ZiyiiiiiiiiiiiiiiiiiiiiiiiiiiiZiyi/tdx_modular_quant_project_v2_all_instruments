# -*- coding: utf-8 -*-
import pandas as pd

from functions.execution.corporate_action_ledger import build_corporate_action_ledger
from functions.pricing.adjustment_pti_audit import build_adjustment_pti_quality_report


def verify_corporate_action_ledger():
    actions = pd.DataFrame(
        [
            {
                "symbol": "sh600000",
                "action_type": "cash_dividend",
                "announcement_date": "2024-01-01",
                "record_date": "2024-01-05",
                "ex_date": "2024-01-08",
                "payment_date": "2024-01-10",
                "revision_timestamp": "2024-01-01 12:00:00",
                "cash_dividend": 0.1,
            }
        ]
    )
    ledger = build_corporate_action_ledger(actions)
    assert bool(ledger.iloc[0]["pit_complete"]) is True
    assert bool(ledger.iloc[0]["unsupported_event_type"]) is False
    audit = build_adjustment_pti_quality_report(pd.DataFrame([{"symbol": "sh600000"}]), actions)
    assert "blocked" in set(audit["status"])
    print("Corporate-action ledger verification passed.")


if __name__ == "__main__":
    verify_corporate_action_ledger()
