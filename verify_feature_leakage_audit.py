# -*- coding: utf-8 -*-
from functions.pricing.feature_leakage_audit import audit_feature_columns


def verify_feature_leakage_audit():
    failures: list[str] = []
    print("=== Verify feature leakage audit skeleton ===")

    clean_columns = [
        "ret_1",
        "ret_5",
        "ma_20",
        "volatility_20",
        "close_nominal",
        "close_adj_forward",
    ]
    clean_labels = {
        "safe_label": {
            "formula": "future close / close - 1",
            "uses_path_dependent_stat": False,
        }
    }
    clean_result = audit_feature_columns(clean_columns, clean_labels)
    if not clean_result["is_clean"]:
        failures.append("clean audit case should have passed")
        print("[FAIL] clean audit case should have passed")
    else:
        print("[PASS] clean audit case passed")

    risky_columns = [
        "ret_1",
        "future_ret_5",
        "reward_classic_forward_return",
        "_ml_target",
    ]
    risky_labels = {
        "bad_label": {
            "formula": "future_max_drawdown / future_ret_20",
            "uses_path_dependent_stat": True,
        }
    }
    risky_result = audit_feature_columns(risky_columns, risky_labels)

    if "future_ret_5" not in risky_result["future_like_feature_columns"]:
        failures.append("future-like column was not detected")
        print("[FAIL] future-like column was not detected")
    else:
        print("[PASS] future-like column detected")

    if "_ml_target" not in risky_result["forbidden_feature_columns"]:
        failures.append("forbidden feature column was not detected")
        print("[FAIL] forbidden feature column was not detected")
    else:
        print("[PASS] forbidden feature column detected")

    if not risky_result["label_metadata_issues"]:
        failures.append("path-dependent label metadata issue was not detected")
        print("[FAIL] path-dependent label metadata issue was not detected")
    else:
        print("[PASS] path-dependent label metadata issue detected")

    if risky_result["is_clean"]:
        failures.append("risky audit case should not be clean")
        print("[FAIL] risky audit case should not be clean")
    else:
        print("[PASS] risky audit case correctly flagged")

    print()
    if failures:
        print("Feature leakage audit verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Feature leakage audit verification passed.")


if __name__ == "__main__":
    verify_feature_leakage_audit()
