# -*- coding: utf-8 -*-
"""Evaluate exploratory governance output against available shared-layer baselines."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from config import GOVERNANCE_OUTPUT_DIR, RESULT_DIR
from functions.decision_council.evaluation import evaluate_phase_two_admission


BASELINES = {
    "mom_lowvol": RESULT_DIR / "backtest_daily_result_mom_lowvol.csv",
    "ml_elasticnet": RESULT_DIR / "backtest_daily_result_ml_elasticnet.csv",
}


def main():
    governance_path = GOVERNANCE_OUTPUT_DIR / "governance_daily_result.csv"
    if not governance_path.exists():
        raise FileNotFoundError(f"Missing governance daily result: {governance_path}")
    manifest = _load_json(GOVERNANCE_OUTPUT_DIR / "environment_manifest.json")
    governance = pd.read_csv(governance_path)
    rows = []
    window_parts = []
    for baseline_name, baseline_path in BASELINES.items():
        if not baseline_path.exists():
            rows.append({"baseline": baseline_name, "status": "missing_baseline"})
            continue
        baseline = pd.read_csv(baseline_path)
        admission = evaluate_phase_two_admission(governance, baseline)
        rows.append(
            {
                "baseline": baseline_name,
                "status": "exploratory_degraded_safety" if manifest.get("safety_proxy_degraded") else "exploratory",
                "eligible_for_phase_two": admission["eligible_for_phase_two"],
                "bootstrap_90pct_lower": admission["bootstrap_90pct_interval"][0],
                "bootstrap_90pct_upper": admission["bootstrap_90pct_interval"][1],
                "governance_max_drawdown": admission["governance_max_drawdown"],
                "baseline_max_drawdown": admission["baseline_max_drawdown"],
                **admission["checks"],
            }
        )
        windows = admission["window_report"].copy()
        windows.insert(0, "baseline", baseline_name)
        window_parts.append(windows)
    output_dir = Path(GOVERNANCE_OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "governance_admission_report.csv"
    windows_path = output_dir / "governance_window_report.csv"
    pd.DataFrame(rows).to_csv(summary_path, index=False, encoding="utf-8-sig")
    (pd.concat(window_parts, ignore_index=True) if window_parts else pd.DataFrame()).to_csv(
        windows_path,
        index=False,
        encoding="utf-8-sig",
    )
    print("Saved governance admission report:", summary_path)
    print("Saved governance window report:", windows_path)


def _load_json(path):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


if __name__ == "__main__":
    main()
