# -*- coding: utf-8 -*-
import pandas as pd

from functions.labels import (
    apply_default_labels,
    build_label_formula_table,
    default_label_specs,
    label_metadata_map,
    validate_label_specs,
)
from functions.pricing.feature_leakage_audit import audit_feature_columns


def verify_labels():
    failures: list[str] = []
    print("=== Verify labels ===")

    specs = default_label_specs()
    required_specs = {
        "future_ret_5",
        "future_ret_10",
        "future_ret_20",
        "binary_updown_label",
        "below_target_penalized_return",
    }
    missing_specs = sorted(required_specs - set(specs))
    if missing_specs:
        failures.append(f"missing label specs: {missing_specs}")
        print(f"[FAIL] missing label specs: {missing_specs}")
    else:
        print("[PASS] default label specs present")

    issues = validate_label_specs(specs)
    if issues:
        failures.extend(issues)
        print(f"[FAIL] label spec validation issues: {issues}")
    else:
        print("[PASS] label spec validation passed")

    formula_table = build_label_formula_table(specs)
    if formula_table.empty:
        failures.append("label formula table should not be empty")
        print("[FAIL] label formula table should not be empty")
    else:
        print("[PASS] label formula table generated")

    sample = pd.DataFrame(
        {
            "symbol": ["sh600000"] * 30 + ["sz000001"] * 30,
            "date": pd.bdate_range("2024-01-01", periods=30).tolist()
            + pd.bdate_range("2024-01-01", periods=30).tolist(),
            "close": list(range(10, 40)) + list(range(20, 50)),
        }
    )
    labeled = apply_default_labels(sample)
    expected_columns = required_specs
    missing_label_columns = sorted(expected_columns - set(labeled.columns))
    if missing_label_columns:
        failures.append(f"missing generated label columns: {missing_label_columns}")
        print(f"[FAIL] missing generated label columns: {missing_label_columns}")
    else:
        print("[PASS] default labels generated")

    metadata_map = label_metadata_map(specs)
    audit_result = audit_feature_columns(
        feature_columns=["ret_1", "ma_20", "volume_ma_5"],
        label_metadata_map=metadata_map,
    )
    if not audit_result["is_clean"]:
        failures.append(f"label metadata unexpectedly failed audit: {audit_result}")
        print(f"[FAIL] label metadata unexpectedly failed audit: {audit_result}")
    else:
        print("[PASS] label metadata passes leakage audit")

    if labeled["binary_updown_label"].dropna().isin([0, 1]).all():
        print("[PASS] binary_updown_label values are binary")
    else:
        failures.append("binary_updown_label contains non-binary values")
        print("[FAIL] binary_updown_label contains non-binary values")

    print()
    if failures:
        print("Label verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Label verification passed.")


if __name__ == "__main__":
    verify_labels()
