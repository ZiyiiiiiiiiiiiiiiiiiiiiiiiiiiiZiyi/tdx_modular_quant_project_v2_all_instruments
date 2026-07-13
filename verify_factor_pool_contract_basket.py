"""Verify factor-pool contract and basket smoke wiring."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from functions.decision_council.governance_smoke_runner import run_contract_basket_smoke
from functions.factors.factor_candidate_pool import CANDIDATE_FACTOR_SPECS


SUMMARY_PATH = Path(
    "results/decision_council/fast_factor_judge/"
    "hs300_csi500_a500_strict/run20260701_201606_233579/fast_factor_summary.csv"
)


def main() -> int:
    if len(CANDIDATE_FACTOR_SPECS) != 7000:
        print(f"[FAIL] candidate factor count should be 7000: {len(CANDIDATE_FACTOR_SPECS)}")
        return 1
    print(f"[PASS] candidate factor count={len(CANDIDATE_FACTOR_SPECS)}")
    if not SUMMARY_PATH.exists():
        print(f"[SKIP] historical fast factor summary not found: {SUMMARY_PATH}")
        return 0
    summary = pd.read_csv(SUMMARY_PATH)
    rejected_grid = set(
        summary.loc[
            summary["factor_name"].astype(str).str.startswith("candidate_grid_", na=False)
            & summary["verdict"].astype(str).eq("reject_or_rework"),
            "factor_name",
        ].astype(str)
    )
    registered = {spec.factor_name for spec in CANDIDATE_FACTOR_SPECS}
    leaked = registered & rejected_grid
    if leaked:
        print(f"[FAIL] rejected grid factors leaked back into registry: {len(leaked)}")
        return 1
    print("[PASS] rejected historical grid factors excluded")
    result = run_contract_basket_smoke(
        SUMMARY_PATH,
        output_dir="reports/verify_factor_pool_contract_basket",
    )
    admitted = int(result.get("admitted_count", 0))
    role_count = int(result.get("role_count", 0))
    basket_name_count = int(result.get("basket_name_count", 0))
    entry_allowed = bool(result.get("entry_allowed", False))
    if admitted < 600:
        print(f"[FAIL] admitted factor count below expected 600: {admitted}")
        return 1
    if role_count < 5:
        print(f"[FAIL] role coverage below 5: {role_count}")
        return 1
    if basket_name_count < 3 or not entry_allowed:
        print(f"[FAIL] basket smoke failed: names={basket_name_count}, entry_allowed={entry_allowed}")
        return 1
    print(f"[PASS] admitted={admitted}, roles={role_count}, basket_names={basket_name_count}, entry_allowed={entry_allowed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
