"""Verify the fast factor judge route.

Run:
& "C:\\Users\\Ziyi Wang\\.conda\\envs\\stock_ai\\python.exe" verify_fast_factor_judge.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from config import REPORT_DIR
from functions.decision_council.fast_factor_judge import run_fast_factor_judge


def _sample_feature_path() -> Path:
    output_dir = REPORT_DIR / "verify_fast_factor_judge"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "sample_fast_factor_features.parquet"
    dates = pd.bdate_range("2024-01-01", periods=145)
    symbols = [f"sh60{i:04d}" for i in range(12)]
    rows = []
    for symbol_index, symbol in enumerate(symbols):
        price = 10.0 + symbol_index
        for day_index, date in enumerate(dates):
            drift = 0.0002 * symbol_index
            cycle = 0.001 * np.sin(day_index / 9.0 + symbol_index)
            price *= 1.0 + drift + cycle
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "instrument_type": "stock",
                    "close": price,
                    "close_nominal": price,
                    "amount": 30_000_000.0 + day_index * 10_000.0 + symbol_index * 100_000.0,
                    "ret_20": day_index / len(dates) + symbol_index / 20.0,
                    "cand_price_momentum_20": day_index / len(dates) + symbol_index / 20.0,
                    "cand_reversal_5": -cycle,
                    "cand_amount_rank_20": symbol_index / len(symbols),
                    "is_trading": True,
                }
            )
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def main() -> int:
    feature_path = _sample_feature_path()
    saved = run_fast_factor_judge(
        universe_name="all_a_share_research",
        start_date="2024-01-01",
        end_date="2024-12-31",
        max_days=120,
        feature_path=feature_path,
        output_dir=REPORT_DIR / "verify_fast_factor_judge" / "outputs",
        max_factor_count=220,
    )
    required = [
        "fast_factor_validation_report",
        "fast_factor_summary",
        "governance_factor_registry_snapshot",
        "governance_factor_cluster_report",
        "fast_factor_judge_report",
        "fast_factor_judge_manifest_json",
    ]
    failures = []
    for key in required:
        path = saved.get(key)
        if path is None or not Path(path).exists():
            failures.append(f"missing output: {key}")
    summary = pd.read_csv(saved["fast_factor_summary"])
    validation = pd.read_csv(saved["fast_factor_validation_report"])
    if summary.empty:
        failures.append("fast factor summary is empty")
    if "cost_adjusted_top_bottom_spread" not in validation.columns:
        failures.append("validation missing cost-adjusted spread")
    for column in ["run_id", "run_created_at", "universe_name", "analysis_start_date", "analysis_end_date"]:
        if column not in validation.columns:
            failures.append(f"validation missing run metadata column: {column}")
    if "pre_screen_candidate" not in set(validation.get("candidate_pool", pd.Series(dtype=str)).astype(str)):
        failures.append("validation missing pre_screen_candidate rows")
    manifest = pd.read_csv(saved["fast_factor_judge_manifest"])
    run_ids = set(manifest.get("run_id", pd.Series(dtype=str)).astype(str))
    if not run_ids or not all(run_id.startswith("run") and len(run_id) >= 20 for run_id in run_ids):
        failures.append("manifest run_id is not timestamped enough for duplicate prevention")
    if failures:
        for failure in failures:
            print(f"[FAIL] {failure}")
        return 1
    for key in required:
        print(f"[PASS] {key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
