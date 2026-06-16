# -*- coding: utf-8 -*-
from pathlib import Path

import pandas as pd

from config import MODEL_TRAINING_DIAGNOSTICS_CSV


REQUIRED_COLUMNS = {
    "model_family",
    "strategy_id",
    "rebalance_date",
    "lookback_days",
    "required_min_train_rows",
    "actual_train_rows",
    "predict_rows",
    "status",
    "skip_reason",
}


def verify_model_training_diagnostics():
    failures: list[str] = []
    print("=== Verify model training diagnostics ===")

    path = Path(MODEL_TRAINING_DIAGNOSTICS_CSV)
    if not path.exists():
        failures.append(f"diagnostics file missing: {path}")
        print(f"[FAIL] diagnostics file missing: {path}")
    else:
        print(f"[PASS] diagnostics file exists: {path}")
        frame = pd.read_csv(path)
        missing = sorted(REQUIRED_COLUMNS - set(frame.columns))
        if missing:
            failures.append(f"diagnostics missing columns: {missing}")
            print(f"[FAIL] diagnostics missing columns: {missing}")
        else:
            print("[PASS] diagnostics columns present")

        if frame.empty:
            failures.append("diagnostics file is empty")
            print("[FAIL] diagnostics file is empty")
        else:
            print(f"[PASS] diagnostics row count: {len(frame)}")

        statuses = set(frame.get("status", pd.Series(dtype=str)).astype(str))
        if "scored" not in statuses:
            failures.append("diagnostics never record scored status")
            print("[FAIL] diagnostics never record scored status")
        else:
            print("[PASS] diagnostics record scored status")

        skipped = frame[frame.get("status", pd.Series(dtype=str)).astype(str) == "skipped"].copy()
        if skipped.empty:
            print("[PASS] diagnostics schema can represent skip reasons even when this run had none")
        else:
            skip_reasons = set(skipped.get("skip_reason", pd.Series(dtype=str)).astype(str))
            if not any(reason in skip_reasons for reason in {"insufficient_train_rows", "empty_train_or_predict", "no_feature_columns"}):
                failures.append("diagnostics do not expose expected skip reasons")
                print("[FAIL] diagnostics do not expose expected skip reasons")
            else:
                print("[PASS] diagnostics expose expected skip reasons")

    print()
    if failures:
        print("Model training diagnostics verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Model training diagnostics verification passed.")


if __name__ == "__main__":
    verify_model_training_diagnostics()
