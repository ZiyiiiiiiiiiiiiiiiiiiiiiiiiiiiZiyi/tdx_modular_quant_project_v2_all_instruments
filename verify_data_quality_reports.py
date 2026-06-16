# -*- coding: utf-8 -*-
from pathlib import Path

import pandas as pd

from config import ADJUSTMENT_PTI_QUALITY_CSV, DATA_CONTINUITY_REPORT_CSV


def verify_data_quality_reports():
    failures: list[str] = []
    print("=== Verify data quality reports ===")

    continuity_path = Path(DATA_CONTINUITY_REPORT_CSV)
    if not continuity_path.exists():
        failures.append(f"missing continuity report: {continuity_path}")
        print(f"[FAIL] missing continuity report: {continuity_path}")
    else:
        continuity = pd.read_csv(continuity_path)
        required = {
            "symbol",
            "rows",
            "max_calendar_gap_days",
            "large_gap_count",
            "has_large_gap",
            "continuity_status",
        }
        missing = sorted(required - set(continuity.columns))
        if missing:
            failures.append(f"continuity report missing columns: {missing}")
            print(f"[FAIL] continuity report missing columns: {missing}")
        else:
            print("[PASS] continuity report columns present")
        if "__summary__" not in set(continuity.get("symbol", pd.Series(dtype=str)).astype(str)):
            failures.append("continuity report missing __summary__ row")
            print("[FAIL] continuity report missing __summary__ row")
        else:
            print("[PASS] continuity report summary row present")

    pti_path = Path(ADJUSTMENT_PTI_QUALITY_CSV)
    if not pti_path.exists():
        failures.append(f"missing adjustment pti coverage report: {pti_path}")
        print(f"[FAIL] missing adjustment pti coverage report: {pti_path}")
    else:
        pti = pd.read_csv(pti_path)
        required = {
            "symbol",
            "rows",
            "covered_rows",
            "coverage_ratio",
            "coverage_status",
            "feature_price_source",
        }
        missing = sorted(required - set(pti.columns))
        if missing:
            failures.append(f"adjustment pti coverage report missing columns: {missing}")
            print(f"[FAIL] adjustment pti coverage report missing columns: {missing}")
        else:
            print("[PASS] adjustment pti coverage report columns present")
        statuses = set(pti.get("coverage_status", pd.Series(dtype=str)).astype(str))
        if not statuses.intersection({"full_coverage", "partial_coverage", "no_coverage"}):
            failures.append("adjustment pti coverage report missing expected coverage statuses")
            print("[FAIL] adjustment pti coverage report missing expected coverage statuses")
        else:
            print("[PASS] adjustment pti coverage statuses present")

    print()
    if failures:
        print("Data quality reports verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Data quality reports verification passed.")


if __name__ == "__main__":
    verify_data_quality_reports()
