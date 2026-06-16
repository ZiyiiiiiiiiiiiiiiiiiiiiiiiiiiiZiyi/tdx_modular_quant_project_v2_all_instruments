# -*- coding: utf-8 -*-
import pandas as pd

from functions.feature_engineering import build_feature_frame, finalize_feature_frame_for_storage


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
        "adjustment_coverage_ratio",
        "adjustment_coverage_threshold",
        "price_basis_selection_mode",
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

    partial_adjusted_sample = sample.copy()
    partial_adjusted_sample["backward_factor"] = 1.0
    partial_adjusted_sample.loc[partial_adjusted_sample["symbol"] == "sz000001", "backward_factor"] = pd.NA
    partial_adjusted_result = build_feature_frame(partial_adjusted_sample)
    partial_price_sources = set(partial_adjusted_result["feature_price_source"].dropna())
    if partial_price_sources != {"nominal_unadjusted"}:
        failures.append("partial adjustment coverage should force a nominal_unadjusted feature basis")
        print("[FAIL] partial adjustment coverage did not force nominal_unadjusted pricing")
    else:
        print("[PASS] partial adjustment coverage falls back to a uniform nominal price basis")
    partial_coverage = pd.to_numeric(partial_adjusted_result["adjustment_coverage_ratio"], errors="coerce").dropna()
    if partial_coverage.empty or not (0.0 < partial_coverage.iloc[0] < 1.0):
        failures.append("partial adjustment coverage ratio should be recorded between 0 and 1")
        print("[FAIL] partial adjustment coverage ratio not recorded correctly")
    else:
        print("[PASS] partial adjustment coverage ratio recorded explicitly")

    stored_result, memory_report = finalize_feature_frame_for_storage(result)
    if "macd_dif" in stored_result.columns or "kdj_rsv" in stored_result.columns:
        failures.append("transient feature columns should be pruned from the stored feature frame")
        print("[FAIL] transient feature columns were not pruned from storage")
    else:
        print("[PASS] transient feature columns pruned from stored feature frame")
    if "score_macd_cross" not in stored_result.columns or "atr_20" not in stored_result.columns:
        failures.append("stored feature frame should retain precomputed strategy columns")
        print("[FAIL] stored feature frame lost required precomputed strategy columns")
    else:
        print("[PASS] stored feature frame retains required strategy columns")
    saved_ratio = pd.to_numeric(memory_report["memory_saved_ratio"], errors="coerce").dropna()
    if saved_ratio.empty:
        failures.append("feature memory report should record memory_saved_ratio")
        print("[FAIL] feature memory report did not record memory_saved_ratio")
    else:
        print("[PASS] feature memory report recorded memory savings")

    print()
    if failures:
        print("Feature pipeline integration verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Feature pipeline integration verification passed.")


if __name__ == "__main__":
    verify_feature_pipeline_integration()
