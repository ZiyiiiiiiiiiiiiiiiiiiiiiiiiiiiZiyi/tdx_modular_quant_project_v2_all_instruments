"""Product checks for dated index snapshot ingestion and PIT compression."""
from __future__ import annotations

from pathlib import Path
import tempfile

import pandas as pd

from functions.data_sources.historical_index_membership import (
    compress_snapshots_to_pit,
    load_a500_snapshot_file,
    normalize_snapshot_frame,
    reconstruct_a500_snapshots_from_current,
    validate_snapshot_coverage,
)


def _snapshots(dates):
    rows = []
    counts = {"000300": 300, "000905": 500, "000510": 500}
    for date in dates:
        for index_code, count in counts.items():
            for number in range(count):
                rows.append({
                    "snapshot_date": date,
                    "provider_update_date": date,
                    "index_code": index_code,
                    "symbol": f"sh{number:06d}",
                    "membership_weight": 1.0,
                    "source": "test_history",
                    "source_document_id": f"test:{date}:{index_code}:{number}",
                    "downloaded_at": pd.Timestamp("2026-07-22", tz="UTC"),
                })
    return normalize_snapshot_frame(pd.DataFrame(rows))


def main():
    dates = [pd.Timestamp("2025-01-02"), pd.Timestamp("2025-01-03")]
    snapshots = _snapshots(dates)
    coverage = validate_snapshot_coverage(snapshots, dates)
    assert coverage["passed"].all()
    intervals = compress_snapshots_to_pit(snapshots, dates)
    assert set(intervals["index_code"]) == {"000300", "000905", "000510"}
    assert len(intervals) == 1300
    assert intervals["known_at"].le(intervals["effective_from"]).all()
    local_current = Path("data/processed/index_constituents.parquet")
    if local_current.exists():
        reconstructed = reconstruct_a500_snapshots_from_current(dates)
        assert reconstructed.groupby("snapshot_date")["symbol"].nunique().eq(500).all()
        assert reconstructed["source"].eq("csindex_periodic_reverse_reconstruction_research").all()

    broken = snapshots[~(
        snapshots["snapshot_date"].eq(dates[1])
        & snapshots["index_code"].eq("000510")
        & snapshots["symbol"].eq("sh000499")
    )]
    failed = validate_snapshot_coverage(broken, dates)
    assert not failed["passed"].all()
    try:
        compress_snapshots_to_pit(broken, dates)
    except ValueError as exc:
        assert "coverage is incomplete" in str(exc)
    else:
        raise AssertionError("incomplete A500 coverage must fail closed")

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "a500.csv"
        pd.DataFrame({"trade_date": ["2025-01-02"], "con_code": ["000001.SZ"]}).to_csv(path, index=False)
        loaded = load_a500_snapshot_file(path)
        assert loaded.iloc[0]["index_code"] == "000510"
        assert loaded.iloc[0]["symbol"] == "sz000001"

        undated = Path(folder) / "undated.csv"
        pd.DataFrame({"code": ["000001.SZ"]}).to_csv(undated, index=False)
        try:
            load_a500_snapshot_file(undated)
        except ValueError as exc:
            assert "dated snapshot" in str(exc)
        else:
            raise AssertionError("undated current snapshot must be rejected")
    print("Historical index membership verification passed.")


if __name__ == "__main__":
    main()
