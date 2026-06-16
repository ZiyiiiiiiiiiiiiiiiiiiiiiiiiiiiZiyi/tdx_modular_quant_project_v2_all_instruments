# -*- coding: utf-8 -*-
from pathlib import Path

import pandas as pd

from config import KELLY_PRIOR_SENSITIVITY_CSV, KELLY_PRIOR_SENSITIVITY_MD


def verify_kelly_prior_sensitivity():
    failures: list[str] = []
    print("=== Verify Kelly prior sensitivity ===")

    csv_path = Path(KELLY_PRIOR_SENSITIVITY_CSV)
    md_path = Path(KELLY_PRIOR_SENSITIVITY_MD)
    if not csv_path.exists():
        failures.append(f"missing Kelly prior sensitivity CSV: {csv_path}")
        print(f"[FAIL] missing Kelly prior sensitivity CSV: {csv_path}")
    else:
        frame = pd.read_csv(csv_path)
        required_columns = {
            "strategy_id",
            "prior_p",
            "prior_strength",
            "wins",
            "losses",
            "posterior_mean",
            "posterior_lower_bound",
            "payoff_ratio",
            "kelly_mean",
            "kelly_lower_bound",
        }
        missing = sorted(required_columns - set(frame.columns))
        if missing:
            failures.append(f"Kelly prior sensitivity CSV missing columns: {missing}")
            print(f"[FAIL] Kelly prior sensitivity CSV missing columns: {missing}")
        else:
            print("[PASS] Kelly prior sensitivity CSV columns present")
        if not frame.empty and frame.groupby("strategy_id")["prior_strength"].nunique().min() < 2:
            failures.append("Kelly prior sensitivity should test multiple prior strengths per strategy")
            print("[FAIL] Kelly prior sensitivity did not vary prior_strength enough")
        else:
            print("[PASS] Kelly prior sensitivity varies prior_strength values")

    if not md_path.exists():
        failures.append(f"missing Kelly prior sensitivity Markdown report: {md_path}")
        print(f"[FAIL] missing Kelly prior sensitivity Markdown report: {md_path}")
    else:
        text = md_path.read_text(encoding="utf-8")
        required_sections = {"## Summary", "## Records"}
        missing_sections = sorted(section for section in required_sections if section not in text)
        if missing_sections:
            failures.append(f"Kelly prior sensitivity report missing sections: {missing_sections}")
            print(f"[FAIL] Kelly prior sensitivity report missing sections: {missing_sections}")
        else:
            print("[PASS] Kelly prior sensitivity report sections present")

    print()
    if failures:
        print("Kelly prior sensitivity verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Kelly prior sensitivity verification passed.")


if __name__ == "__main__":
    verify_kelly_prior_sensitivity()
