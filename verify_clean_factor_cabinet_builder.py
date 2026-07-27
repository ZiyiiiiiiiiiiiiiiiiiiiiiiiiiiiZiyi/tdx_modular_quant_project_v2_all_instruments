from __future__ import annotations

import json
from pathlib import Path
import tempfile

import pandas as pd

from functions.factor_selection.clean_factor_cabinet_builder import build_clean_factor_cabinets


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    source = root / "source"
    source.mkdir()
    payload = {
        "run_id": "source_test",
        "analysis_end_date": "2024-02-29",
        "factors": [
            {"factor_name": "old_value", "raw_column": "old_value", "family": "valuation", "role": "entry_alpha"},
            {"factor_name": "old_growth", "raw_column": "old_growth", "family": "growth", "role": "entry_alpha_proxy"},
        ],
    }
    cabinet = source / "factor_cabinet.json"
    cabinet.write_text(json.dumps(payload), encoding="utf-8")
    candidate = pd.DataFrame([{
        "factor_name": "earnings_yield_ttm", "raw_column": "pit_earnings_yield_ttm",
        "family": "valuation", "role": "entry_alpha_proxy", "coverage": 0.9,
        "best_ic_ir": 0.5, "positive_ic_ratio": 0.7,
        "best_cost_adjusted_top_bottom_spread": 0.02, "negative_control_pass": True,
    }])
    paths = build_clean_factor_cabinets(
        source_cabinet_path=cabinet, oos_start="2024-02-01",
        removed_factors=["old_value"], observed_candidates=candidate,
        available_columns=["pit_earnings_yield_ttm"], pit_level2_state="available",
        output_root=root / "out_overlap",
    )
    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    check(not summary["formal_eligible"], "overlapping discovery lineage is research-only")
    check(summary["formal_factor_count"] == 0, "overlap produces no formal cabinet factors")
    check(summary["replacement_count"] == 0, "overlap blocks replacement evidence")

    payload["analysis_end_date"] = "2023-11-30"
    cabinet.write_text(json.dumps(payload), encoding="utf-8")
    paths = build_clean_factor_cabinets(
        source_cabinet_path=cabinet, oos_start="2024-02-01",
        removed_factors=["old_value"], observed_candidates=candidate,
        available_columns=["pit_earnings_yield_ttm"], pit_level2_state="available",
        output_root=root / "out_clean",
    )
    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    research = json.loads(paths["research_factor_cabinet"].read_text(encoding="utf-8"))
    check(summary["formal_eligible"], "clean lineage plus PIT Level-2 permits formal artifact")
    check(summary["replacement_count"] == 1, "qualified same-family valuation factor fills vacancy")
    check(any(row["factor_name"] == "earnings_yield_ttm" for row in research["factors"]), "replacement is written into cabinet")

print("Clean factor cabinet builder checks passed.")
