"""Verify factor cabinet builder output contract."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from functions.factor_selection.factor_cabinet_builder import build_factor_cabinet


def main() -> int:
    saved = build_factor_cabinet(
        min_factors=60,
        max_factors=120,
        output_root=Path("reports/verify_factor_cabinet_builder/factor_cabinet"),
    )
    output = Path(saved["output_dir"])
    required = [
        "factor_cabinet.json",
        "factor_cabinet.csv",
        "factor_cabinet_report.md",
        "near_relative_dedup_report.csv",
        "correlation_cluster_report.csv",
        "role_quota_report.csv",
    ]
    missing = [name for name in required if not (output / name).exists()]
    if missing:
        print(f"[FAIL] missing cabinet outputs: {missing}")
        return 1
    cabinet = pd.read_csv(output / "factor_cabinet.csv")
    if not (60 <= len(cabinet) <= 120):
        print(f"[FAIL] cabinet size outside 60-120: {len(cabinet)}")
        return 1
    if "cabinet_role" not in cabinet.columns:
        print("[FAIL] cabinet_role missing")
        return 1
    print(f"[PASS] cabinet output={output}, factors={len(cabinet)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
