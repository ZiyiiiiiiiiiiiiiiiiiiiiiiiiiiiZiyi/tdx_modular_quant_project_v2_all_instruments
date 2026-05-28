# -*- coding: utf-8 -*-
import pandas as pd

from functions.factors.advanced_price_volume import compute_advanced_price_volume_features


def verify_advanced_price_volume():
    failures: list[str] = []
    print("=== Verify advanced price volume factors ===")

    sample = pd.DataFrame(
        {
            "symbol": ["sh600000"] * 30,
            "date": pd.bdate_range("2024-01-01", periods=30),
            "open": range(10, 40),
            "high": range(11, 41),
            "low": range(9, 39),
            "close": range(10, 40),
            "volume": range(100, 130),
        }
    )
    result = compute_advanced_price_volume_features(sample)
    required = {"gap_1", "breakout_strength_20", "pullback_depth_20", "volume_shock_20"}
    missing = sorted(required - set(result.columns))
    if missing:
        failures.append(f"missing advanced feature columns: {missing}")
        print(f"[FAIL] missing advanced feature columns: {missing}")
    else:
        print("[PASS] advanced feature columns generated")

    print()
    if failures:
        print("Advanced price volume verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Advanced price volume verification passed.")


if __name__ == "__main__":
    verify_advanced_price_volume()
