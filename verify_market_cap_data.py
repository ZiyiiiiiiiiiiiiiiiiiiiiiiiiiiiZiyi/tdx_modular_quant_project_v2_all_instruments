# -*- coding: utf-8 -*-
import tempfile
from pathlib import Path

import pandas as pd

from functions.data_sources.market_cap_data import (
    REQUIRED_MARKET_CAP_COLUMNS,
    build_market_cap_quality_report,
    detect_market_cap_jump_flags,
    fill_stabilized_market_cap,
    normalize_market_cap_history,
    save_market_cap_history,
    save_market_cap_quality_report,
)


def _check_columns(frame, required_columns, label, failures):
    missing = sorted(set(required_columns) - set(frame.columns))
    if missing:
        failures.append(f"{label} missing columns: {missing}")
        print(f"[FAIL] {label}: missing columns {missing}")
    else:
        print(f"[PASS] {label}: required columns present")


def verify_market_cap_data():
    failures: list[str] = []
    print("=== Verify market cap data ===")

    raw_df = pd.DataFrame(
        {
            "external_code": ["600000.SH", "600000.SH", "000001.SZ", "000001.SZ"],
            "market": ["sh", "sh", "sz", "sz"],
            "code": ["600000", "600000", "000001", "000001"],
            "date": ["2024-01-02", "2024-01-03", "2024-01-02", "2024-01-03"],
            "total_cap": [1000, 1400, 2000, 2050],
            "float_cap": [600, 900, 1100, 1120],
            "jump_event_type": ["", "unlock", "", ""],
        }
    )

    normalized = normalize_market_cap_history(raw_df, source_name="synthetic_market_cap")
    _check_columns(normalized, REQUIRED_MARKET_CAP_COLUMNS, "market cap history", failures)

    if normalized["symbol"].isna().any():
        failures.append("normalized market cap history contains missing symbols")
        print("[FAIL] normalized market cap history contains missing symbols")
    else:
        print("[PASS] normalized market cap history symbols populated")

    flagged = detect_market_cap_jump_flags(normalized, jump_ratio=0.20)
    jump_rows = int(flagged["market_cap_jump_flag"].fillna(False).sum())
    float_jump_rows = int(flagged["float_cap_jump_flag"].fillna(False).sum())
    if jump_rows <= 0:
        failures.append("expected at least one market cap jump row")
        print("[FAIL] expected at least one market cap jump row")
    else:
        print(f"[PASS] market cap jump rows detected: {jump_rows}")

    if float_jump_rows <= 0:
        failures.append("expected at least one float cap jump row")
        print("[FAIL] expected at least one float cap jump row")
    else:
        print(f"[PASS] float cap jump rows detected: {float_jump_rows}")

    stabilized = fill_stabilized_market_cap(flagged)
    if stabilized["stabilized_total_cap"].isna().any():
        failures.append("stabilized_total_cap should not contain NaN")
        print("[FAIL] stabilized_total_cap should not contain NaN")
    else:
        print("[PASS] stabilized_total_cap populated")

    if stabilized["stabilized_float_cap"].isna().any():
        failures.append("stabilized_float_cap should not contain NaN")
        print("[FAIL] stabilized_float_cap should not contain NaN")
    else:
        print("[PASS] stabilized_float_cap populated")

    report = build_market_cap_quality_report(stabilized)
    if report.empty:
        failures.append("market cap quality report should not be empty")
        print("[FAIL] market cap quality report should not be empty")
    else:
        print("[PASS] market cap quality report generated")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        parquet_path = save_market_cap_history(stabilized, tmp / "market_cap_history.parquet")
        report_path = save_market_cap_quality_report(stabilized, tmp / "market_cap_quality_report.csv")
        if not parquet_path.exists():
            failures.append(f"market cap parquet missing after save: {parquet_path}")
            print(f"[FAIL] market cap parquet missing after save: {parquet_path}")
        else:
            print(f"[PASS] market cap parquet saved: {parquet_path}")

        if not report_path.exists():
            failures.append(f"market cap quality report missing after save: {report_path}")
            print(f"[FAIL] market cap quality report missing after save: {report_path}")
        else:
            print(f"[PASS] market cap quality report saved: {report_path}")

    print()
    if failures:
        print("Market cap data verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Market cap data verification passed.")


if __name__ == "__main__":
    verify_market_cap_data()
