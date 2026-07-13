from __future__ import annotations

from pathlib import Path

import pandas as pd

from functions.data.pit_level1_builder import build_security_master_pit, build_trading_status_pit, write_pit_table_atomic
from functions.data.pit_level1_store import load_pit_snapshot, run_pit_preflight


def main() -> None:
    root = Path("reports/verify_pit_level1_builder/store")
    securities = build_security_master_pit(pd.DataFrame([
        {"code": "sh.600000", "code_name": "A", "ipoDate": "1999-11-10", "outDate": None},
    ]), downloaded_at="2024-03-01")
    statuses = build_trading_status_pit(pd.DataFrame([
        {"date": "2024-02-01", "code": "sh.600000", "tradestatus": "1", "isST": "0"},
        {"date": "2024-02-02", "code": "sh.600000", "tradestatus": "0", "isST": "1"},
    ]), downloaded_at="2024-03-01")
    write_pit_table_atomic(securities, table_name="security_master_pit", root=root)
    write_pit_table_atomic(statuses, table_name="trading_status_pit", root=root)
    snapshot = load_pit_snapshot("trading_status_pit", root=root, as_of="2024-02-02", effective_on="2024-02-02")
    assert len(snapshot) == 1 and bool(snapshot.iloc[0]["is_st"])
    research = run_pit_preflight(mode="research", root=root)
    assert research["pit_runtime_state"] == "degraded"
    try:
        run_pit_preflight(mode="formal", root=root)
    except Exception:
        pass
    else:
        raise AssertionError("formal PIT preflight must fail when required tables are missing")
    print("[PASS] free-source PIT normalization, atomic storage, as-of, and fail-closed preflight")


if __name__ == "__main__":
    main()
