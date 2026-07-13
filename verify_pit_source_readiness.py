from __future__ import annotations

from pathlib import Path
import tempfile

import pandas as pd

from functions.data.pit_level1_builder import build_trading_status_pit, write_pit_table_atomic
from functions.data.pit_level1_store import run_pit_preflight
from functions.data.pit_source_readiness import audit_existing_pit_sources


def main() -> None:
    readiness = audit_existing_pit_sources().set_index("target_table")
    assert bool(readiness.loc["corporate_action_pit", "research_reusable"])
    assert not bool(readiness.loc["corporate_action_pit", "formal_eligible"])
    assert "known-at" in readiness.loc["corporate_action_pit", "limitation"]
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        status = build_trading_status_pit(
            pd.DataFrame([{"date": "2024-01-02", "symbol": "sh600000", "is_trading": True, "is_st": False}])
        )
        write_pit_table_atomic(
            status,
            table_name="trading_status_pit",
            root=root,
            formal_eligible=False,
            provenance={"limitation": "derived"},
        )
        audit = run_pit_preflight(mode="research", root=root)
        assert "trading_status_pit" in audit["formal_ineligible_tables"]
        assert not audit["formal_pass"]
    print("[PASS] existing PIT-like artifacts are reusable only with explicit formal blockers")


if __name__ == "__main__":
    main()
