"""Verify Financial/Event PIT Level-2 contracts without external data."""
from __future__ import annotations

import pandas as pd

from functions.data.pit_level2_store import (
    PitLevel2UnavailableError,
    run_pit_level2_preflight,
    validate_pit_level2_frame,
)


def _financial_frame() -> pd.DataFrame:
    return pd.DataFrame([{
        "symbol": "sh600000", "report_period": "2023-12-31", "statement_type": "annual",
        "period_value_basis": "ytd",
        "known_at": "2024-03-20 18:00:00", "effective_from": "2024-03-21",
        "source": "cninfo", "source_document_id": "doc-1", "revision_id": "v1",
        "downloaded_at": "2024-03-21", "revenue": 100.0, "net_profit": 10.0,
        "deducted_net_profit": 9.0, "gross_profit": 30.0, "operating_profit": 12.0,
        "operating_cashflow": 11.0, "capex": 3.0, "total_assets": 200.0,
        "total_equity": 80.0, "industry": "bank",
    }])


def main() -> int:
    audit = validate_pit_level2_frame(_financial_frame(), table_name="financial_statement_pit")
    assert audit["passed"].all(), audit
    leaked = _financial_frame()
    leaked["effective_from"] = "2024-03-19"
    leaked_audit = validate_pit_level2_frame(leaked, table_name="financial_statement_pit")
    assert not bool(leaked_audit.loc[leaked_audit["check"].eq("effective_not_before_known"), "passed"].iloc[0])
    research = run_pit_level2_preflight(mode="research", root="reports/verify_missing_pit_level2")
    assert research["pit_runtime_state"] == "degraded"
    try:
        run_pit_level2_preflight(mode="formal", root="reports/verify_missing_pit_level2")
    except PitLevel2UnavailableError:
        pass
    else:
        raise AssertionError("formal PIT Level-2 accepted missing tables")
    print("[PASS] PIT Level-2 schemas reject leakage and formal mode fails closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
