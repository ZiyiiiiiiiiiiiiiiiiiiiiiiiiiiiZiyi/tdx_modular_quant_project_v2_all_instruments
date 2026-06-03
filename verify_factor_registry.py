# -*- coding: utf-8 -*-
import pandas as pd

from functions.factor_registry import default_factor_registry, factor_registry_frame
from functions.factor_tests import build_factor_test_report


def verify_factor_registry():
    failures: list[str] = []
    print("=== Verify factor registry ===")

    registry = default_factor_registry()
    frame = factor_registry_frame(registry)
    if frame.empty:
        failures.append("factor registry frame should not be empty")
        print("[FAIL] factor registry frame should not be empty")
    else:
        print("[PASS] factor registry frame generated")

    if frame["factor_name"].duplicated().any():
        failures.append("factor registry names must be unique")
        print("[FAIL] factor registry names must be unique")
    else:
        print("[PASS] factor registry names are unique")

    sample = pd.DataFrame(
        {
            "ret_1": [0.1, 0.2, None],
            "ret_5": [0.1, None, 0.3],
            "ret_10": [0.2, 0.1, 0.0],
            "ret_20": [0.3, 0.1, 0.1],
            "ret_60": [0.2, 0.2, 0.2],
        }
    )
    report = build_factor_test_report("momentum_core", sample, registry["momentum_core"].output_columns)
    coverage = report["coverage"]
    if coverage.empty:
        failures.append("factor test coverage should not be empty")
        print("[FAIL] factor test coverage should not be empty")
    else:
        print("[PASS] factor test coverage generated")

    print()
    if failures:
        print("Factor registry verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Factor registry verification passed.")


if __name__ == "__main__":
    verify_factor_registry()
