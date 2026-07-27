"""Product verification for the PIT-safe monthly LightGBM ranker contract."""
from __future__ import annotations

import numpy as np
import pandas as pd

from functions.decision_council.monthly_lgbm_hybrid import (
    PENDING_FEATURE_SPECS,
    OnlineMonthlyLGBMController,
    apply_continuous_rank_fusion,
    attach_cross_sectional_relevance,
    build_excess_return_labels,
    calibrate_fusion_weight,
    feature_contract_table,
    fit_monthly_lgbm_ranker,
    predict_daily_rank,
)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def synthetic_training_frame() -> pd.DataFrame:
    rng = np.random.default_rng(20260717)
    dates = pd.bdate_range("2023-01-02", periods=90)
    rows = []
    for date_idx, date in enumerate(dates):
        for symbol_idx in range(24):
            trend = rng.normal()
            orderflow = rng.normal()
            rows.append(
                {
                    "date": date,
                    "symbol": f"S{symbol_idx:03d}",
                    "trend": trend,
                    "orderflow": orderflow,
                    "label_maturity_date": dates[min(date_idx + 5, len(dates) - 1)],
                    "future_excess_log_return_net": 0.018 * trend + 0.012 * orderflow + rng.normal(0, 0.008),
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    price_dates = pd.bdate_range("2024-01-02", periods=12)
    prices = pd.DataFrame(
        [
            {"date": date, "symbol": symbol, "close": 10.0 + i + (0.2 if symbol == "B" else 0.0)}
            for symbol in ("A", "B")
            for i, date in enumerate(price_dates)
        ]
    )
    labels = build_excess_return_labels(prices, horizon_days=5, round_trip_cost_rate=0.002)
    first = labels[(labels["symbol"] == "A") & (labels["date"] == price_dates[0])].iloc[0]
    check(first["label_maturity_date"] == price_dates[5], "label maturity date is the future observation date")
    check(np.isclose(first["future_excess_log_return_net"], np.log(15.0 / 10.0) + np.log(0.998)), "label formula deducts round-trip cost")
    variable_prices = prices.copy()
    variable_prices["open"] = variable_prices["close"] + 0.1
    variable_prices["estimated_round_trip_cost_rate"] = variable_prices["symbol"].map({"A": 0.001, "B": 0.02})
    variable = build_excess_return_labels(variable_prices, horizon_days=5, round_trip_cost_rate=0.0)
    variable_first = variable[variable["date"].eq(price_dates[0])].set_index("symbol")
    check(
        variable_first.loc["A", "label_entry_price"] == variable_prices.loc[
            variable_prices["symbol"].eq("A"), "open"
        ].iloc[1],
        "close-time decisions use the next executable session open",
    )
    check(
        variable_first.loc["A", "label_round_trip_cost_rate"]
        < variable_first.loc["B", "label_round_trip_cost_rate"],
        "stock-specific costs survive into the ranking label",
    )
    relevance = attach_cross_sectional_relevance(labels, bins=5)
    check(relevance["ml_relevance"].dropna().between(0, 4).all(), "LambdaRank relevance is bounded and integer-compatible")

    frame = synthetic_training_frame()
    frame["cabinet_family_size_style_score"] = (
        frame.groupby("date", sort=False)["trend"].rank(pct=True, method="average")
    )
    as_of = pd.Timestamp("2023-04-28")
    immature = frame["label_maturity_date"].gt(as_of).sum()
    artifact = fit_monthly_lgbm_ranker(
        frame,
        feature_columns=("trend", "orderflow", "cabinet_family_size_style_score"),
        as_of_date=as_of,
        horizon_days=5,
        validation_date_count=15,
        model_params={"n_estimators": 60},
    )
    check(immature > 0, "synthetic product test contains labels unavailable at cutoff")
    check(artifact.training_rows + artifact.validation_rows < len(frame), "unmatured and purged labels cannot enter model fit")
    check(artifact.runtime_model == "lightgbm.LGBMRanker", "runtime model is real LightGBM, not a proxy")
    check(artifact.objective == "lambdarank", "model uses the cross-sectional ranking objective")
    check(
        artifact.parameter_selection_status in {
            "nested_purged_one_standard_error",
            "nested_purged_early_stopped_cost_aware_one_standard_error",
            "data_scaled_fallback_insufficient_inner_dates",
            "data_scaled_fallback_empty_inner_split",
            "data_scaled_fallback_inner_ic_unavailable",
            "pre_registered_explicit_params",
        }
        and bool(artifact.selected_model_params),
        "tree capacity is selected by inner purged data, a disclosed data-scaled fallback, or explicit preregistration",
    )
    auto_artifact = fit_monthly_lgbm_ranker(
        frame,
        feature_columns=("trend", "orderflow"),
        as_of_date=as_of,
        horizon_days=5,
        validation_date_count=15,
    )
    check(
        auto_artifact.parameter_selection_status.startswith(("nested_purged", "data_scaled"))
        and bool(auto_artifact.selected_model_params),
        "automatic tree parameters are selected without using the outer validation window",
    )
    check(
        auto_artifact.best_iteration > 0
        and not auto_artifact.iteration_metrics.empty
        and {"train", "outer_valid"}.issubset(set(auto_artifact.iteration_metrics["dataset"])),
        "boosting rounds and train/locked-validation learning curves are persisted",
    )
    if auto_artifact.parameter_selection_status.startswith("nested_purged"):
        check(
            not auto_artifact.nested_candidate_metrics.empty
            and {"best_iteration", "ndcg_at_5", "top5_turnover_proxy", "selected"}.issubset(
                auto_artifact.nested_candidate_metrics.columns
            ),
            "inner early stopping and cost-aware candidate comparison are auditable",
        )
    check(artifact.validation_rank_ic_mean > 0.0, "out-of-sample validation rank IC detects the planted signal")
    daily = frame[frame["date"] == frame["date"].max()].copy()
    predicted = predict_daily_rank(artifact, daily)
    check(predicted["monthly_lgbm_rank_percentile"].between(0.0, 1.0).all(), "daily ML output is a continuous percentile")
    check(
        predicted["expected_edge_5d"].notna().all()
        and predicted["conservative_expected_edge_5d"].notna().all(),
        "locked validation calibrates ordinal ranks into bounded five-day return units",
    )
    check("entry_confirmed" not in predicted.columns, "ML module cannot approve or veto an entry")
    schema_drift_daily = daily.drop(columns="cabinet_family_size_style_score")
    schema_aligned = predict_daily_rank(artifact, schema_drift_daily)
    check(
        schema_aligned["monthly_lgbm_raw_score"].notna().all()
        and schema_aligned["monthly_lgbm_schema_imputed_feature_count"].eq(1).all()
        and schema_aligned["monthly_lgbm_schema_imputed_features"].eq(
            "cabinet_family_size_style_score"
        ).all(),
        "a dynamically absent cabinet family is aligned to the locked training schema and audited",
    )
    fixed_feature_error = ""
    try:
        predict_daily_rank(artifact, daily.drop(columns="orderflow"))
    except ValueError as exc:
        fixed_feature_error = str(exc)
    check(
        "orderflow" in fixed_feature_error,
        "a missing fixed ML feature remains a hard contract error",
    )
    validation = frame[frame["date"].isin(sorted(frame["date"].unique())[-20:])].copy()
    validation["rule_score"] = -validation["trend"] + np.random.default_rng(7).normal(0, 0.3, len(validation))
    validation["ml_score"] = validation["trend"] + validation["orderflow"]
    calibration = calibrate_fusion_weight(
        validation,
        rule_score_column="rule_score",
        ml_score_column="ml_score",
        maximum_ml_weight=0.40,
        horizon_days=5,
    )
    check(0.0 < calibration.ml_weight <= calibration.maximum_ml_weight, "formula-derived ML weight respects its pre-registered ceiling")
    fusion_input = validation[validation["date"] == validation["date"].max()].copy()
    fusion_input["cabinet_native_final_score"] = fusion_input["rule_score"]
    fusion_input["monthly_lgbm_raw_score"] = fusion_input["ml_score"]
    fused = apply_continuous_rank_fusion(fusion_input, calibration)
    expected = (1.0 - calibration.ml_weight) * fused["hybrid_rule_rank_percentile"] + calibration.ml_weight * fused["hybrid_ml_rank_percentile"]
    check(np.allclose(fused["hybrid_final_score"], expected), "hybrid score follows the declared continuous fusion formula")
    check("entry_confirmed" not in fused.columns, "fusion module changes ranking only, never the entry decision")
    negative = validation.copy()
    negative["ml_score"] = -negative["future_excess_log_return_net"]
    fallback = calibrate_fusion_weight(
        negative,
        rule_score_column="rule_score",
        ml_score_column="ml_score",
        maximum_ml_weight=0.40,
        horizon_days=5,
    )
    fallback_input = fusion_input.drop(columns="monthly_lgbm_raw_score")
    fallback_fused = apply_continuous_rank_fusion(fallback_input, fallback)
    check(fallback.ml_weight == 0.0, "non-positive validation IC removes ML authority")
    check(np.allclose(fallback_fused["hybrid_final_score"], fallback_fused["hybrid_rule_rank_percentile"]), "unhealthy model falls back exactly to cabinet ranking")
    online_dates = pd.bdate_range("2023-01-02", periods=70)
    online_prices = []
    for date_index, date in enumerate(online_dates):
        online_prices.append({"date": date, "symbol": "BENCH", "close": 100.0 * (1.0005 ** date_index)})
        for symbol_index in range(10):
            online_prices.append({
                "date": date, "symbol": f"O{symbol_index:02d}",
                "close": (10.0 + symbol_index) * ((1.0002 + symbol_index * 0.00015) ** date_index),
            })
    online_prices = pd.DataFrame(online_prices)
    controller = OnlineMonthlyLGBMController(
        maximum_ml_weight=0.40,
        benchmark_symbol="BENCH",
        horizon_days=5,
        validation_date_count=10,
        minimum_training_date_count=30,
        round_trip_cost_rate=0.002,
        model_params={"n_estimators": 30},
    )
    saw_cold_start = False
    saw_model = False
    all_online_scores_valid = True
    for date in online_dates:
        day = pd.DataFrame({
            "date": date,
            "symbol": [f"O{i:02d}" for i in range(10)],
            "cabinet_native_final_score": np.linspace(0.1, 0.9, 10),
            "cabinet_strict_entry_score": np.linspace(0.1, 0.9, 10),
            "cabinet_proxy_entry_score": np.linspace(0.2, 0.8, 10),
            "cabinet_timing_score": np.linspace(0.3, 0.7, 10),
            "cabinet_risk_safety_score": 0.6,
            "cabinet_liquidity_health_score": 0.7,
            "cabinet_hold_support_score": 0.5,
            "ret_5": np.linspace(-0.03, 0.03, 10),
            "ret_20": np.linspace(-0.05, 0.05, 10),
        })
        online_scored, online_audit = controller.process_day(day, as_of_date=date, price_history=online_prices)
        saw_cold_start |= online_audit["status"] == "fallback_insufficient_matured_history"
        saw_model |= bool(online_audit["model_available"])
        all_online_scores_valid &= bool(online_scored["hybrid_final_score"].notna().all())
    check(all_online_scores_valid, "online controller produces valid scores throughout cold start and active months")
    check(saw_cold_start, "online monthly controller fails safely during cold start")
    check(saw_model, "online monthly controller activates after enough labels mature")
    prepared_columns = controller._available_feature_columns(pd.DataFrame({
        "cabinet_hold_support_score": [0.5],
        "candidate_rank": [1],
        "cabinet_family_value_score": [0.5],
        "cabinet_family_momentum_score": [0.5],
    }))
    check("cabinet_hold_support_score" not in prepared_columns, "hold-only evidence cannot rank new entries")
    check("candidate_rank" not in prepared_columns, "ML cannot relearn the rule rank through an endogenous rank feature")
    check("cabinet_family_value_score" not in prepared_columns, "PIT-restricted families fail closed by default")
    check("cabinet_family_momentum_score" in prepared_columns, "PIT-safe market families remain available")
    attempts = controller.training_attempt_frame()
    check(attempts["as_of"].max() <= online_dates.max(), "monthly training audit never exceeds the decision cutoff")
    selected_attempts = attempts[attempts.get("parameter_selection_status", pd.Series(index=attempts.index, dtype=object)).notna()]
    check(
        not selected_attempts.empty
        and selected_attempts["parameter_selection_status"].astype(str).str.startswith(("nested_purged", "data_scaled", "pre_registered")).all(),
        "monthly training records nested, data-scaled, or explicit preregistered parameter selection",
    )
    check(
        not controller.iteration_metric_frame().empty,
        "online monthly controller retains per-iteration learning curves",
    )
    contract = feature_contract_table()
    check(len(PENDING_FEATURE_SPECS) == 6, "six unjudged fundamental/event families remain explicitly pending")
    check(set(contract.loc[contract["status"] == "pending", "family"]) == {"valuation", "profitability", "investment", "cashflow", "growth", "event"}, "pending family disclosure is complete")
    print("[PASS] monthly LightGBM module product verification completed")


if __name__ == "__main__":
    main()
