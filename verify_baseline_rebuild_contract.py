# -*- coding: utf-8 -*-
import tempfile
from pathlib import Path

import pandas as pd

from compare_old_new_rankings import (
    REQUIRED_COMPARISON_COLUMNS,
    build_rank_shift_report,
    save_rank_shift_report,
)
from rebuild_all_baselines import build_rebuild_plan, publish_current_summary
from functions.strategy_registry import list_strategy_names


def _check_columns(frame, required_columns, label, failures):
    missing = sorted(set(required_columns) - set(frame.columns))
    if missing:
        failures.append(f"{label} missing columns: {missing}")
        print(f"[FAIL] {label}: missing columns {missing}")
    else:
        print(f"[PASS] {label}: required columns present")


def verify_baseline_rebuild_contract():
    failures: list[str] = []
    print("=== Verify baseline rebuild contract ===")

    plan = build_rebuild_plan()
    if plan["strategy_count"] <= 0:
        failures.append("rebuild plan strategy_count must be positive")
        print("[FAIL] rebuild plan strategy_count must be positive")
    else:
        print(f"[PASS] rebuild plan strategy_count: {plan['strategy_count']}")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        current = pd.DataFrame(
            {"strategy": list_strategy_names(), "total_return": 0.0, "sharpe": 0.0, "composite_score": 0.0}
        )
        current_path = tmp / "current.csv"
        current.to_csv(current_path, index=False)
        summary_path = publish_current_summary(current_path, tmp / "summary_v2.csv")
        summary_df = pd.read_csv(summary_path)
        if "baseline_status" not in summary_df.columns:
            failures.append("published summary missing baseline_status column")
            print("[FAIL] published summary missing baseline_status column")
        else:
            print("[PASS] published summary identifies baseline status")

        old_summary = pd.DataFrame(
            {
                "strategy": ["alpha", "beta"],
                "total_return": [0.10, 0.05],
                "sharpe": [1.0, 0.8],
                "composite_score": [90, 80],
            }
        )
        new_summary = pd.DataFrame(
            {
                "strategy": ["alpha", "beta"],
                "total_return": [0.08, 0.12],
                "sharpe": [0.9, 1.1],
                "composite_score": [70, 95],
            }
        )
        old_path = tmp / "old.csv"
        new_path = tmp / "new.csv"
        old_summary.to_csv(old_path, index=False, encoding="utf-8-sig")
        new_summary.to_csv(new_path, index=False, encoding="utf-8-sig")

        report = build_rank_shift_report(old_path, new_path)
        _check_columns(report, REQUIRED_COMPARISON_COLUMNS, "rank shift report", failures)

        alpha_shift = float(report.loc[report["strategy"] == "alpha", "rank_shift"].iloc[0])
        beta_shift = float(report.loc[report["strategy"] == "beta", "rank_shift"].iloc[0])
        if alpha_shift == 0 or beta_shift == 0:
            failures.append("expected non-zero rank shift for synthetic summaries")
            print("[FAIL] expected non-zero rank shift for synthetic summaries")
        else:
            print("[PASS] synthetic rank shifts detected")

        report_file = save_rank_shift_report(report, tmp / "rank_shift.csv")
        if not report_file.exists():
            failures.append(f"rank shift report missing after save: {report_file}")
            print(f"[FAIL] rank shift report missing after save: {report_file}")
        else:
            print(f"[PASS] rank shift report saved: {report_file}")

    print()
    if failures:
        print("Baseline rebuild contract verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Baseline rebuild contract verification passed.")


if __name__ == "__main__":
    verify_baseline_rebuild_contract()
