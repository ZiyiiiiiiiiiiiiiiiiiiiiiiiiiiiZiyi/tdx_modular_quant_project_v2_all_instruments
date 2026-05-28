# -*- coding: utf-8 -*-
import pandas as pd

from functions.feature_engineering import build_feature_frame


def verify_feature_pipeline_integration():
    failures: list[str] = []
    print("=== Verify feature pipeline integration ===")

    sample_dates = pd.bdate_range("2024-01-01", periods=150)
    rows = []
    for symbol, start in [("sh600000", 10), ("sz000001", 20)]:
        for idx, date in enumerate(sample_dates):
            price = start + idx * 0.1
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "market": symbol[:2],
                    "code": symbol[2:],
                    "instrument_type": "stock",
                    "open": price,
                    "high": price * 1.01,
                    "low": price * 0.99,
                    "close": price * 1.005,
                    "amount": 100000 + idx * 100,
                    "volume": 1000 + idx,
                    "is_trading": True,
                    "abnormal_jump": False,
                }
            )
    sample = pd.DataFrame(rows)

    result = build_feature_frame(sample)
    required = {
        "future_ret_5",
        "binary_updown_label",
        "below_target_penalized_return",
        "close_nominal",
        "feature_price_source",
        "feature_timestamp",
        "ret_20_z",
        "ret_20_robust",
        "ret_20_neutralized",
        "score_mom_lowvol_z",
    }
    missing = sorted(required - set(result.columns))
    if missing:
        failures.append(f"missing integrated feature columns: {missing}")
        print(f"[FAIL] missing integrated feature columns: {missing}")
    else:
        print("[PASS] integrated label and normalization columns generated")

    if set(result["feature_price_source"].dropna()) != {"nominal_unadjusted"}:
        failures.append("feature frame without factors should be marked nominal_unadjusted")
        print("[FAIL] unadjusted feature price source was not marked")
    else:
        print("[PASS] unadjusted feature price source marked explicitly")

    if result["future_ret_5"].notna().sum() <= 0:
        failures.append("future_ret_5 should have non-null rows")
        print("[FAIL] future_ret_5 should have non-null rows")
    else:
        print("[PASS] future_ret_5 populated")

    if result["ret_20_z"].notna().sum() <= 0:
        failures.append("ret_20_z should have non-null rows")
        print("[FAIL] ret_20_z should have non-null rows")
    else:
        print("[PASS] ret_20_z populated")

    adjusted_sample = sample.copy()
    adjusted_sample["backward_factor"] = 1.0
    adjusted_sample.loc[
        (adjusted_sample["symbol"] == "sh600000") & (adjusted_sample["date"] >= sample_dates[-5]),
        "backward_factor",
    ] = 2.0
    adjusted_result = build_feature_frame(adjusted_sample)
    if set(adjusted_result["feature_price_source"].dropna()) != {"adjusted_point_in_time"}:
        failures.append("available factor column should select point-in-time adjusted feature prices")
        print("[FAIL] adjusted feature price source was not selected")
    else:
        print("[PASS] adjusted feature price source selected when factors exist")

    print()
    if failures:
        print("Feature pipeline integration verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Feature pipeline integration verification passed.")


if __name__ == "__main__":
    verify_feature_pipeline_integration()
