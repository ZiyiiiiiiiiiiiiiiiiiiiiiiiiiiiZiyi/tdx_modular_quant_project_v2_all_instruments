# -*- coding: utf-8 -*-
import tempfile
from pathlib import Path

import pandas as pd

from functions.data_sources.event_data import (
    REQUIRED_EVENT_DATA_COLUMNS,
    normalize_event_data,
    save_event_data,
    save_event_data_quality_report,
)


def verify_event_data():
    failures: list[str] = []
    print("=== Verify event data ===")

    raw_df = pd.DataFrame(
        {
            "external_code": ["600000.SH", "000001.SZ"],
            "market": ["sh", "sz"],
            "code": ["600000", "000001"],
            "event_date": ["2024-01-05", "2024-01-06"],
            "event_type": ["earnings_notice", "risk_warning"],
            "event_title": ["notice", "warning"],
        }
    )
    normalized = normalize_event_data(raw_df, source_name="synthetic_event")
    missing = sorted(set(REQUIRED_EVENT_DATA_COLUMNS) - set(normalized.columns))
    if missing:
        failures.append(f"event data missing columns: {missing}")
        print(f"[FAIL] event data missing columns: {missing}")
    else:
        print("[PASS] event data normalized")

    with tempfile.TemporaryDirectory() as tmpdir:
        parquet_path = save_event_data(normalized, Path(tmpdir) / "event.parquet")
        report_path = save_event_data_quality_report(normalized, Path(tmpdir) / "event_report.csv")
        if not parquet_path.exists() or not report_path.exists():
            failures.append("event data outputs missing after save")
            print("[FAIL] event data outputs missing after save")
        else:
            print("[PASS] event data outputs saved")

    print()
    if failures:
        print("Event data verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Event data verification passed.")


if __name__ == "__main__":
    verify_event_data()
