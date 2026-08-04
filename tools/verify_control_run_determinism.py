"""Compare two frozen-control SCAP runs on business semantics.

Volatile UUID columns are excluded explicitly. Floating-point diagnostics are
compared with a tight absolute tolerance; all remaining fields must match.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


FILES = {
    "governance_daily_result.csv": set(),
    "governance_execution_ledger.csv": {"order_id", "fill_id"},
    "governance_action_proposal_ledger.csv": set(),
    "governance_strategy_summary.csv": set(),
    "governance_trade_pairs.csv": {"entry_order_id", "sell_order_id"},
}


def _canonical(frame: pd.DataFrame, excluded: set[str]) -> pd.DataFrame:
    return frame.drop(columns=sorted(excluded & set(frame.columns))).reset_index(drop=True)


def _compare(left: pd.DataFrame, right: pd.DataFrame) -> dict:
    if list(left.columns) != list(right.columns) or left.shape != right.shape:
        return {
            "passed": False,
            "shape_left": list(left.shape),
            "shape_right": list(right.shape),
            "reason": "schema_or_shape_mismatch",
        }
    mismatches: dict[str, dict] = {}
    max_abs_diff = 0.0
    for column in left.columns:
        a_num = pd.to_numeric(left[column], errors="coerce")
        b_num = pd.to_numeric(right[column], errors="coerce")
        numeric_mask = a_num.notna() | b_num.notna()
        if numeric_mask.all():
            a_num = a_num.astype(float)
            b_num = b_num.astype(float)
            diff = (a_num - b_num).abs()
            current_max = float(diff.max()) if len(diff) else 0.0
            max_abs_diff = max(max_abs_diff, current_max)
            bad = ~np.isclose(a_num, b_num, rtol=1e-12, atol=1e-12, equal_nan=True)
        else:
            bad = left[column].fillna("<NA>").astype(str).ne(
                right[column].fillna("<NA>").astype(str)
            )
        count = int(bad.sum())
        if count:
            mismatches[column] = {"mismatch_rows": count}
    canonical_bytes = left.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return {
        "passed": not mismatches,
        "rows": int(len(left)),
        "columns": int(len(left.columns)),
        "max_abs_numeric_difference": max_abs_diff,
        "semantic_sha256_left": hashlib.sha256(canonical_bytes).hexdigest(),
        "mismatches": mismatches,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    results = {}
    for filename, excluded in FILES.items():
        left = _canonical(pd.read_csv(args.left / filename, low_memory=False), excluded)
        right = _canonical(pd.read_csv(args.right / filename, low_memory=False), excluded)
        result = _compare(left, right)
        result["excluded_volatile_columns"] = sorted(excluded)
        results[filename] = result
    payload = {
        "schema_version": "scap_control_determinism_v1",
        "left": str(args.left),
        "right": str(args.right),
        "tolerance": {"rtol": 1e-12, "atol": 1e-12},
        "passed": all(item["passed"] for item in results.values()),
        "files": results,
        "interpretation": (
            "Business ledgers are deterministic after excluding UUID-only keys; "
            "floating-point diagnostics are equal within machine precision."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": payload["passed"], "output": str(args.output)}))
    raise SystemExit(0 if payload["passed"] else 1)


if __name__ == "__main__":
    main()
