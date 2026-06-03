# -*- coding: utf-8 -*-
import tempfile
from pathlib import Path

import pandas as pd

from functions.data_sources.adjustment_factors import (
    REQUIRED_ADJUSTMENT_FACTOR_COLUMNS,
    attach_adjustment_factors_to_daily,
    build_adjustment_factors,
    build_adjustment_factors_quality_report,
    save_adjustment_factors,
    save_adjustment_factors_quality_report,
    normalize_provider_adjustment_factors,
)
from functions.data_sources.corporate_actions import normalize_corporate_actions


def _build_synthetic_actions():
    return pd.DataFrame(
        [
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
                "external_code": "600000.SH",
                "market": "sh",
                "code": "600000",
                "action_date": "2024-12-31",
                "action_type": "stock_dividend",
                "cash_dividend": 0.0,
                "stock_dividend_ratio": 0.2,
                "rights_issue_ratio": 0.0,
                "rights_issue_price": None,
                "notes": "synthetic row 2",
            },
            {
                "external_code": "000001.SZ",
                "market": "sz",
                "code": "000001",
                "action_date": "2024-07-15",
                "action_type": "rights_issue",
                "cash_dividend": 0.0,
                "stock_dividend_ratio": 0.0,
                "rights_issue_ratio": 0.1,
                "rights_issue_price": 8.5,
                "notes": "synthetic row 3",
            },
        ]
    )


def _check_columns(frame, required_columns, label, failures):
    missing = sorted(set(required_columns) - set(frame.columns))
    if missing:
        failures.append(f"{label} missing columns: {missing}")
        print(f"[FAIL] {label}: missing columns {missing}")
    else:
        print(f"[PASS] {label}: required columns present")


def verify_adjustment_factors():
    failures: list[str] = []
    print("=== Verify adjustment factors skeleton ===")

    actions_df = normalize_corporate_actions(_build_synthetic_actions(), source_name="synthetic")
    factors_df = build_adjustment_factors(actions_df)
    _check_columns(
        factors_df,
        REQUIRED_ADJUSTMENT_FACTOR_COLUMNS,
        "adjustment factors",
        failures,
    )

    if factors_df.empty:
        failures.append("adjustment factors frame is empty")
        print("[FAIL] adjustment factors frame is empty")
    else:
        print(f"[PASS] adjustment factors rows: {len(factors_df)}")

    if factors_df["factor_source_validated"].any():
        failures.append("corporate action rows without provider factors must be invalid")
        print("[FAIL] event-only rows incorrectly created validated price factors")
    else:
        print("[PASS] event-only rows cannot create synthetic price factors")

    provider_raw = pd.DataFrame(
        {
            "external_code": ["sh.600000", "sh.600000"],
            "dividOperateDate": ["2024-06-30", "2024-12-31"],
            "foreAdjustFactor": [None, 1.0],
            "backAdjustFactor": [1.2, 1.4],
        }
    )
    provider_df = normalize_provider_adjustment_factors(provider_raw)
    if not provider_df["factor_source_validated"].all():
        failures.append("provider factors should validate")
        print("[FAIL] supplied provider factors not validated")
    else:
        print("[PASS] provider-supplied factors validate")
    daily = pd.DataFrame(
        {"symbol": ["sh600000", "sh600000"], "date": pd.to_datetime(["2024-06-28", "2024-07-01"])}
    )
    attached = attach_adjustment_factors_to_daily(daily, provider_df)
    if bool(attached.loc[0, "adj_factor_available"]) or not bool(attached.loc[1, "adj_factor_available"]):
        failures.append("point-in-time factor availability is incorrect")
        print("[FAIL] point-in-time factor availability is incorrect")
    else:
        print("[PASS] point-in-time factor attachment does not backfill future events")

    quality_df = build_adjustment_factors_quality_report(factors_df)
    if quality_df.empty:
        failures.append("adjustment factors quality report is empty")
        print("[FAIL] adjustment factors quality report is empty")
    else:
        print("[PASS] adjustment factors quality report generated")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        factors_file = save_adjustment_factors(factors_df, tmp_path / "adjustment_factors.parquet")
        quality_file = save_adjustment_factors_quality_report(
            factors_df,
            tmp_path / "adjustment_factors_quality_report.csv",
        )
        for label, file_path in [
            ("adjustment factors parquet", factors_file),
            ("adjustment factors quality report", quality_file),
        ]:
            if Path(file_path).exists():
                print(f"[PASS] {label}: {file_path}")
            else:
                failures.append(f"{label} missing after save: {file_path}")
                print(f"[FAIL] {label}: missing {file_path}")

    print()
    if failures:
        print("Adjustment factors verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Adjustment factors verification passed.")


if __name__ == "__main__":
    verify_adjustment_factors()
