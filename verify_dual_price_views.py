# -*- coding: utf-8 -*-
import pandas as pd

from functions.pricing.price_transform import (
    forward_adjusted_to_nominal,
    nominal_to_forward_adjusted,
)
from functions.pricing.price_views import (
    ADJUSTED_PRICE_COLUMNS,
    NOMINAL_PRICE_COLUMNS,
    build_dual_price_view,
    validate_dual_price_columns,
)


def verify_dual_price_views():
    failures: list[str] = []
    print("=== Verify dual price views skeleton ===")

    base = pd.DataFrame(
        {
            "date": ["2024-06-28", "2024-06-30"],
            "symbol": ["sh600000", "sh600000"],
            "open": [10.0, 10.5],
            "high": [10.2, 10.8],
            "low": [9.8, 10.3],
            "close": [10.1, 10.6],
            "forward_factor": [1.0, 1.2],
        }
    )

    dual = build_dual_price_view(base, factor_col="forward_factor")
    missing_columns = validate_dual_price_columns(dual)
    if missing_columns:
        failures.append(f"missing dual price columns: {missing_columns}")
        print(f"[FAIL] missing dual price columns: {missing_columns}")
    else:
        print("[PASS] dual price columns generated")

    for col in ["open", "high", "low", "close"]:
        if col not in dual.columns:
            failures.append(f"original price column missing after dual view build: {col}")
            print(f"[FAIL] original price column missing after dual view build: {col}")
    if not any("original price column missing" in item for item in failures):
        print("[PASS] original price columns preserved")

    first_row_ok = dual.loc[0, "close_nominal"] == dual.loc[0, "close"]
    if not first_row_ok:
        failures.append("nominal close does not match original close")
        print("[FAIL] nominal close does not match original close")
    else:
        print("[PASS] nominal close matches original close")

    adjusted_expected = 10.6 * 1.2
    adjusted_actual = float(dual.loc[1, "close_adj_forward"])
    if round(adjusted_actual, 6) != round(adjusted_expected, 6):
        failures.append("adjusted close does not match expected transformed close")
        print("[FAIL] adjusted close does not match expected transformed close")
    else:
        print("[PASS] adjusted close matches expected transformed close")

    transformed = nominal_to_forward_adjusted(base["close"], base["forward_factor"])
    restored = forward_adjusted_to_nominal(transformed, base["forward_factor"])
    if not restored.round(10).equals(pd.to_numeric(base["close"]).round(10)):
        failures.append("price transform round-trip failed")
        print("[FAIL] price transform round-trip failed")
    else:
        print("[PASS] price transform round-trip succeeded")

    if list(NOMINAL_PRICE_COLUMNS) == list(ADJUSTED_PRICE_COLUMNS):
        failures.append("nominal and adjusted column contracts collided")
        print("[FAIL] nominal and adjusted column contracts collided")
    else:
        print("[PASS] nominal and adjusted column contracts are distinct")

    partial = base.copy()
    partial.loc[1, "forward_factor"] = None
    partial_dual = build_dual_price_view(partial, factor_col="forward_factor")
    if pd.notna(partial_dual.loc[1, "close_adj_forward"]) or bool(partial_dual.loc[1, "adj_factor_available"]):
        failures.append("missing factor silently fell back to nominal price")
        print("[FAIL] missing factor silently fell back to nominal price")
    else:
        print("[PASS] missing adjustment factor is explicitly unavailable")

    print()
    if failures:
        print("Dual price views verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Dual price views verification passed.")


if __name__ == "__main__":
    verify_dual_price_views()
