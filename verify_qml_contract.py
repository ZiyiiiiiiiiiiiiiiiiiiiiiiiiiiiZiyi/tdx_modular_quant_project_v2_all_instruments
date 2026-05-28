# -*- coding: utf-8 -*-
from functions.qml_experiments.qml_contract import build_qml_exit_criteria, build_qml_experiment_registry


def verify_qml_contract():
    failures: list[str] = []
    print("=== Verify QML contract ===")

    criteria = build_qml_exit_criteria()
    if criteria["min_test_windows"] <= 0:
        failures.append("min_test_windows must be positive")
        print("[FAIL] min_test_windows must be positive")
    else:
        print("[PASS] qml exit criteria generated")

    registry = build_qml_experiment_registry()
    if registry.empty:
        failures.append("qml experiment registry should not be empty")
        print("[FAIL] qml experiment registry should not be empty")
    else:
        print("[PASS] qml experiment registry generated")

    print()
    if failures:
        print("QML contract verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("QML contract verification passed.")


if __name__ == "__main__":
    verify_qml_contract()
