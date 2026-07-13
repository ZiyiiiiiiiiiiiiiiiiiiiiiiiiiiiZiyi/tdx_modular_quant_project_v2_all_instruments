"""Verify Factor Appeal Judge v2 RSI-first flow."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from functions.decision_council.factor_appeal_judge import DEFAULT_V1_RUN_DIR, run_factor_appeal_judge
from functions.factor_selection.factor_cabinet_builder import build_factor_cabinet


REQUIRED_FILES = [
    "appeal_summary.csv",
    "admitted_v2.csv",
    "watchlist_v2.csv",
    "rejected_v2.csv",
    "role_distribution_v2.csv",
    "family_distribution_v2.csv",
    "profile_distribution_v2.csv",
    "unmapped_factors.csv",
    "profile_mapping_report.csv",
    "appeal_report.md",
    "appeal_manifest.csv",
]


def main() -> int:
    v1_summary = DEFAULT_V1_RUN_DIR / "fast_factor_summary.csv"
    if not v1_summary.exists():
        print(f"[SKIP] v1 summary not found: {v1_summary}")
        return 0
    before_mtime = v1_summary.stat().st_mtime
    saved = run_factor_appeal_judge(
        max_days=120,
        output_root=Path("reports/verify_factor_appeal_judge"),
    )
    output = Path(saved["output_dir"])
    missing = [name for name in REQUIRED_FILES if not (output / name).exists()]
    if missing:
        print(f"[FAIL] missing appeal outputs: {missing}")
        return 1
    after_mtime = v1_summary.stat().st_mtime
    if before_mtime != after_mtime:
        print("[FAIL] v1 fast factor summary was modified")
        return 1
    summary = pd.read_csv(output / "appeal_summary.csv")
    required_columns = {
        "factor_name",
        "raw_column",
        "direction",
        "parameter_version",
        "factor_family",
        "factor_type",
        "judge_profile",
        "old_decision",
        "new_decision",
        "old_role",
        "new_role",
        "rank_ic",
        "ic_ir",
        "positive_ic_ratio",
        "top_bottom_spread",
        "coverage",
        "reject_reason",
        "promote_reason",
        "watchlist_reason",
    }
    missing_columns = sorted(required_columns - set(summary.columns))
    if missing_columns:
        print(f"[FAIL] appeal summary missing columns: {missing_columns}")
        return 1
    if summary.empty:
        print("[FAIL] appeal summary is empty")
        return 1
    expected_profiles = {"technical_timing", "technical_timing_sparse", "price_fast_orderflow"}
    if not expected_profiles.issubset(set(summary["judge_profile"].astype(str))):
        print("[FAIL] role-aware appeal profiles are incomplete")
        return 1
    if summary["new_role"].astype(str).eq("entry_alpha").any():
        print("[FAIL] RSI appeal assigned entry_alpha")
        return 1
    breakout = summary[summary["factor_type"].eq("breakout")]
    if len(breakout) != 2 or not breakout["new_decision"].eq("promote_candidate").all():
        print("[FAIL] sparse breakout appeal did not promote both validated signals")
        return 1
    if summary.loc[summary["new_decision"].ne("reject_or_rework"), "raw_column"].astype(str).eq("").any():
        print("[FAIL] admitted/watchlist appeal factor missing executable raw_column")
        return 1
    cabinet_saved = build_factor_cabinet(
        appeal_run_dir=output,
        output_root=Path("reports/verify_factor_appeal_judge/factor_cabinet"),
        min_factors=60,
        max_factors=120,
    )
    cabinet = pd.read_csv(cabinet_saved["factor_cabinet_csv"])
    required_breakouts = {"price_volume_breakout", "turtle_breakout"}
    if not required_breakouts.issubset(set(cabinet["factor_name"].astype(str))):
        print("[FAIL] promoted breakout factors did not reach the executable cabinet")
        return 1
    print(f"[PASS] appeal judge output={output}, rows={len(summary)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
