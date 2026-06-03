# -*- coding: utf-8 -*-
from functions.factors.factor_learning import build_learning_baseline_contract
from functions.factors.factor_ml import build_ml_baseline_contract, list_ml_baseline_models


def verify_ml_baselines():
    failures: list[str] = []
    print("=== Verify ML baselines ===")

    models = list_ml_baseline_models()
    if not models:
        failures.append("ML baseline models should not be empty")
        print("[FAIL] ML baseline models should not be empty")
    else:
        print(f"[PASS] ML baseline models: {models}")

    ml_contract = build_ml_baseline_contract()
    learning_contract = build_learning_baseline_contract()
    if ml_contract.empty:
        failures.append("ML baseline contract should not be empty")
        print("[FAIL] ML baseline contract should not be empty")
    else:
        print("[PASS] ML baseline contract generated")

    if learning_contract.empty:
        failures.append("learning baseline contract should not be empty")
        print("[FAIL] learning baseline contract should not be empty")
    else:
        print("[PASS] learning baseline contract generated")

    print()
    if failures:
        print("ML baseline verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("ML baseline verification passed.")


if __name__ == "__main__":
    verify_ml_baselines()
