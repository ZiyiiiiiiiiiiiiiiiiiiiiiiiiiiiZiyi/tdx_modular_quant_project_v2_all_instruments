"""Verify PIT storage fails closed and honors as-of revisions."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd

from functions.data.pit_level1_store import PitDataUnavailableError, load_pit_snapshot, load_pit_table


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        try:
            load_pit_table("trading_status_pit", root=root)
        except PitDataUnavailableError:
            pass
        else:
            raise AssertionError("missing required PIT table did not fail closed")
        frame = pd.DataFrame([
            {"symbol": "sh600000", "effective_from": "2024-01-01", "effective_to": None,
             "known_at": "2024-01-02", "source": "sse", "source_document_id": "a",
             "revision_id": "r1", "downloaded_at": "2024-01-02", "is_trading": True,
             "is_st": False, "status_reason": "normal"},
            {"symbol": "sh600000", "effective_from": "2024-01-01", "effective_to": None,
             "known_at": "2024-01-05", "source": "sse", "source_document_id": "b",
             "revision_id": "r2", "downloaded_at": "2024-01-05", "is_trading": False,
             "is_st": True, "status_reason": "revised"},
        ])
        frame.to_parquet(root / "trading_status_pit.parquet", index=False)
        before = load_pit_snapshot("trading_status_pit", root=root, as_of="2024-01-03")
        after = load_pit_snapshot("trading_status_pit", root=root, as_of="2024-01-06")
        assert bool(before.iloc[0]["is_trading"])
        assert not bool(after.iloc[0]["is_trading"])
    print("[PASS] PIT Level-1 store fails closed and isolates revisions by known_at")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
