# -*- coding: utf-8 -*-
import tempfile
from pathlib import Path

import pandas as pd

from functions.data_sources.code_mapping import (
    REQUIRED_CODE_MAPPING_COLUMNS,
    build_code_mapping_frame,
    save_code_mapping_report,
    summarize_code_mapping,
)
from functions.data_sources.corporate_actions import (
    REQUIRED_CORPORATE_ACTION_COLUMNS,
    build_corporate_actions_quality_report,
    normalize_corporate_actions,
    save_corporate_actions,
    save_corporate_actions_quality_report,
)


def _build_synthetic_records():
    return [
        {
            "external_code": "600000.SH",
            "market": "sh",
            "code": "600000",
            "action_date": "2024-06-30",
            "action_type": "cash_dividend",
            "cash_dividend": 0.12,
            "stock_dividend_ratio": 0.0,
            "rights_issue_ratio": 0.0,
            "rights_issue_price": None,
            "notes": "synthetic row",
        },
        {
            "external_code": "000001.SZ",
            "market": "sz",
            "code": "000001",
            "action_date": "2024-07-15",
            "action_type": "stock_dividend",
            "cash_dividend": 0.0,
            "stock_dividend_ratio": 0.2,
            "rights_issue_ratio": 0.0,
            "rights_issue_price": None,
            "notes": "synthetic row 2",
        },
        {
            "external_code": "MISSING",
            "market": "",
            "code": "",
            "action_date": "2024-07-20",
            "action_type": "rights_issue",
            "cash_dividend": 0.0,
            "stock_dividend_ratio": 0.0,
            "rights_issue_ratio": 0.1,
            "rights_issue_price": 8.5,
            "notes": "synthetic unmapped row",
        },
    ]


def _check_columns(frame, required_columns, label, failures):
    missing = sorted(set(required_columns) - set(frame.columns))
    if missing:
        failures.append(f"{label} missing columns: {missing}")
        print(f"[FAIL] {label}: missing columns {missing}")
    else:
        print(f"[PASS] {label}: required columns present")


def verify_corporate_actions():
    failures: list[str] = []
    print("=== Verify corporate actions skeleton ===")

    records = _build_synthetic_records()
    mapping_df = build_code_mapping_frame(records, source_name="synthetic")
    _check_columns(mapping_df, REQUIRED_CODE_MAPPING_COLUMNS, "code mapping", failures)

    mapping_summary = summarize_code_mapping(mapping_df)
    if mapping_summary["rows"] != len(records):
        failures.append("code mapping row count mismatch")
        print("[FAIL] code mapping row count mismatch")
    else:
        print(f"[PASS] code mapping row count: {mapping_summary['rows']}")

    if mapping_summary["unmapped_rows"] < 1:
        failures.append("expected at least one unmapped synthetic row")
        print("[FAIL] expected at least one unmapped synthetic row")
    else:
        print(f"[PASS] code mapping unmapped rows: {mapping_summary['unmapped_rows']}")

    actions_df = normalize_corporate_actions(pd.DataFrame(records), source_name="synthetic")
    _check_columns(
        actions_df,
        REQUIRED_CORPORATE_ACTION_COLUMNS,
        "corporate actions",
        failures,
    )

    quality_df = build_corporate_actions_quality_report(actions_df)
    if quality_df.empty:
        failures.append("corporate actions quality report is empty")
        print("[FAIL] corporate actions quality report is empty")
    else:
        print("[PASS] corporate actions quality report generated")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        mapping_report = save_code_mapping_report(mapping_df, tmp_path / "code_mapping_report.csv")
        actions_file = save_corporate_actions(actions_df, tmp_path / "corporate_actions.parquet")
        quality_file = save_corporate_actions_quality_report(
            actions_df,
            tmp_path / "corporate_actions_quality_report.csv",
        )

        for label, file_path in [
            ("code mapping report", mapping_report),
            ("corporate actions parquet", actions_file),
            ("corporate actions quality report", quality_file),
        ]:
            if Path(file_path).exists():
                print(f"[PASS] {label}: {file_path}")
            else:
                failures.append(f"{label} missing after save: {file_path}")
                print(f"[FAIL] {label}: missing {file_path}")

    print()
    if failures:
        print("Corporate actions verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Corporate actions verification passed.")


if __name__ == "__main__":
    verify_corporate_actions()
