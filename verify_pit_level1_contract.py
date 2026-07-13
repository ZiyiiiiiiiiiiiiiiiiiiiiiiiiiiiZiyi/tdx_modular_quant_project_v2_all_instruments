"""Verify PIT Level-1 schemas and as-of revision behavior."""
from __future__ import annotations

import pandas as pd

from functions.data.pit_data_contract import free_source_registry_frame, pit_asof, validate_pit_frame


def main() -> int:
    rows = pd.DataFrame([
        {"symbol": "sh600000", "effective_from": "2020-01-01", "effective_to": None,
         "known_at": "2020-01-01", "source": "sse", "source_document_id": "a",
         "revision_id": "v1", "downloaded_at": "2026-01-01", "listing_status": "listed", "security_name": "A"},
        {"symbol": "sh600000", "effective_from": "2020-01-01", "effective_to": None,
         "known_at": "2021-01-01", "source": "sse", "source_document_id": "b",
         "revision_id": "v2", "downloaded_at": "2026-01-01", "listing_status": "listed", "security_name": "A2"},
    ])
    audit = validate_pit_frame(rows, table_name="security_master_pit")
    assert audit["passed"].all(), audit.to_dict("records")
    snapshot = pit_asof(rows, as_of="2020-06-01")
    assert len(snapshot) == 1 and snapshot.iloc[0]["revision_id"] == "v1"
    assert len(free_source_registry_frame()) >= 5
    print("[PASS] PIT Level-1 schema, revision keys, intervals, and as-of isolation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
