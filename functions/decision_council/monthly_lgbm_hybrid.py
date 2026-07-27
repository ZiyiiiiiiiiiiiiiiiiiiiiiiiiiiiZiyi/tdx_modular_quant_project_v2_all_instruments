"""PIT-safe monthly LightGBM ranker for the governance v3 hybrid mainline.

The model in this module is deliberately limited to candidate ranking.  It
does not implement factual trading gates, position sizing, or exits.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

from functions.decision_council.pit_feature_contract import pit_eligible_features
from functions.decision_council.ml_treatment_audit import (
    attach_rank_treatment,
    daily_treatment_summary,
    mature_treatment_effect,
)
from functions.decision_council.ml_nested_validation import (
    cost_aware_rank_objective,
    one_standard_error_choice,
)


MAINLINE_V3_MONTHLY_LGBM_HYBRID = "mainline_v3_monthly_lgbm_hybrid"
ML_FEATURE_CONTRACT_VERSION = "monthly_lgbm_hybrid_features_v1"
ML_LABEL_CONTRACT_VERSION = "future_excess_log_return_net_cost_v1"


@dataclass(frozen=True)
class HybridFeatureSpec:
    """A semantic feature, its accepted source columns, and product status."""

    name: str
    source_columns: tuple[str, ...]
    family: str
    status: str = "available"
    pit_requirement: str = "known_at_decision_time"


HYBRID_FEATURE_SPECS = (
    HybridFeatureSpec("strict_entry_score", ("cabinet_strict_entry_score",), "cabinet_role"),
    HybridFeatureSpec("proxy_entry_score", ("cabinet_proxy_entry_score",), "cabinet_role"),
    HybridFeatureSpec("timing_score", ("cabinet_timing_score",), "cabinet_role"),
    HybridFeatureSpec("risk_safety_score", ("cabinet_risk_safety_score",), "cabinet_role"),
    HybridFeatureSpec("liquidity_health_score", ("cabinet_liquidity_health_score",), "cabinet_role"),
    HybridFeatureSpec("hold_support_score", ("cabinet_hold_support_score",), "cabinet_role"),
    HybridFeatureSpec("ret_5", ("ret_5",), "trend"),
    HybridFeatureSpec("ret_20", ("ret_20",), "trend"),
    HybridFeatureSpec("volatility_20", ("volatility_20",), "risk"),
    HybridFeatureSpec("amount_to_ma20", ("amount_to_ma20", "amount_ma20"), "liquidity"),
    HybridFeatureSpec("close_to_ma20", ("close_to_ma20", "ma_20"), "trend"),
    HybridFeatureSpec(
        "orderflow_proxy",
        ("orderflow_proxy", "cand_orderflow_proxy", "orderflow_score"),
        "orderflow",
    ),
    HybridFeatureSpec("flow_close_location_value", ("flow_close_location_value",), "orderflow"),
    HybridFeatureSpec("flow_accumulation_proxy", ("flow_accumulation_proxy",), "orderflow"),
    HybridFeatureSpec("flow_distribution_proxy", ("flow_distribution_proxy",), "orderflow"),
    HybridFeatureSpec("market_risk_state", ("market_risk_state",), "market_regime"),
    HybridFeatureSpec("current_candidate_rank", ("candidate_rank",), "selection_context"),
)


PENDING_FEATURE_SPECS = (
    HybridFeatureSpec("valuation", ("earnings_yield", "book_to_price", "fcf_yield"), "valuation", "pending", "point_in_time_fundamental"),
    HybridFeatureSpec("profitability", ("roe", "roa", "gross_margin", "operating_margin"), "profitability", "pending", "point_in_time_fundamental"),
    HybridFeatureSpec("investment", ("asset_growth", "capex_intensity"), "investment", "pending", "point_in_time_fundamental"),
    HybridFeatureSpec("cashflow_quality", ("ocf_to_net_income", "accruals", "fcf_yield"), "cashflow", "pending", "point_in_time_fundamental"),
    HybridFeatureSpec("growth_quality", ("growth_acceleration", "growth_stability", "revenue_profit_alignment"), "growth", "pending", "point_in_time_fundamental"),
    HybridFeatureSpec("event", ("earnings_guidance", "buyback", "insider_change", "announcement_window"), "event", "pending", "event_publication_timestamp"),
)


@dataclass
class MonthlyRankerArtifact:
    """In-memory model artifact with enough metadata for reproducible audits."""

    model: object
    feature_columns: tuple[str, ...]
    feature_medians: dict[str, float]
    trained_as_of: pd.Timestamp
    model_month: str
    horizon_days: int
    training_rows: int
    validation_rows: int
    validation_dates: int
    validation_rank_ic_mean: float
    validation_rank_ic_positive_share: float
    contract_version: str = ML_FEATURE_CONTRACT_VERSION
    label_contract_version: str = ML_LABEL_CONTRACT_VERSION
    runtime_model: str = "lightgbm.LGBMRanker"
    objective: str = "lambdarank"
    degradation_flags: list[str] = field(default_factory=list)
    validation_predictions: pd.DataFrame = field(default_factory=pd.DataFrame, repr=False)
    validation_feature_diagnostics: pd.DataFrame = field(default_factory=pd.DataFrame, repr=False)
    selected_model_params: dict[str, object] = field(default_factory=dict)
    parameter_selection_status: str = ""
    best_iteration: int = 0
    iteration_metrics: pd.DataFrame = field(default_factory=pd.DataFrame, repr=False)
    nested_candidate_metrics: pd.DataFrame = field(default_factory=pd.DataFrame, repr=False)
    score_return_calibration: pd.DataFrame = field(default_factory=pd.DataFrame, repr=False)

    def audit_dict(self) -> dict:
        return {
            "model_month": self.model_month,
            "trained_as_of": self.trained_as_of.strftime("%Y-%m-%d"),
            "horizon_days": self.horizon_days,
            "training_rows": self.training_rows,
            "validation_rows": self.validation_rows,
            "validation_dates": self.validation_dates,
            "validation_rank_ic_mean": self.validation_rank_ic_mean,
            "validation_rank_ic_positive_share": self.validation_rank_ic_positive_share,
            "feature_columns": "|".join(self.feature_columns),
            "feature_contract_version": self.contract_version,
            "label_contract_version": self.label_contract_version,
            "runtime_model": self.runtime_model,
            "objective": self.objective,
            "selected_model_params": "|".join(f"{key}={value}" for key, value in sorted(self.selected_model_params.items())),
            "parameter_selection_status": self.parameter_selection_status,
            "best_iteration": self.best_iteration,
            "degradation_flags": "|".join(self.degradation_flags),
        }


@dataclass(frozen=True)
class FusionCalibration:
    """Validation-only calibration for the continuous hybrid rank formula."""

    ml_weight: float
    unconstrained_weight: float
    reliability: float
    maximum_ml_weight: float
    validation_rank_ic_mean: float
    validation_rank_ic_standard_error: float
    status: str
    formula_version: str = "validation_rank_mse_reliability_shrink_v1"

    def audit_dict(self) -> dict:
        return {
            "ml_weight": self.ml_weight,
            "rule_weight": 1.0 - self.ml_weight,
            "unconstrained_weight": self.unconstrained_weight,
            "reliability": self.reliability,
            "maximum_ml_weight": self.maximum_ml_weight,
            "validation_rank_ic_mean": self.validation_rank_ic_mean,
            "validation_rank_ic_standard_error": self.validation_rank_ic_standard_error,
            "status": self.status,
            "formula_version": self.formula_version,
        }


def build_excess_return_labels(
    prices: pd.DataFrame,
    *,
    horizon_days: int,
    benchmark_prices: pd.DataFrame | None = None,
    round_trip_cost_rate: float = 0.0,
    cost_rate_column: str = "estimated_round_trip_cost_rate",
    entry_price_columns: tuple[str, ...] = ("open_nominal", "open"),
) -> pd.DataFrame:
    """Build forward stock-minus-benchmark log returns with an explicit maturity date.

    ``label_maturity_date`` is the date on which the future close becomes known.
    Training code must filter it against its information cutoff.
    """
    required = {"date", "symbol", "close"}
    missing = sorted(required - set(prices.columns))
    if missing:
        raise ValueError(f"label prices are missing columns: {missing}")
    horizon = int(horizon_days)
    if horizon <= 0:
        raise ValueError("horizon_days must be positive")
    data = prices.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["close"] = pd.to_numeric(data["close"], errors="coerce")
    data = data.dropna(subset=["date", "symbol", "close"]).sort_values(["symbol", "date"])
    grouped = data.groupby("symbol", sort=False)
    data["future_close"] = grouped["close"].shift(-horizon)
    data["label_maturity_date"] = grouped["date"].shift(-horizon)
    entry_column = next((column for column in entry_price_columns if column in data.columns), "")
    if entry_column:
        data[entry_column] = pd.to_numeric(data[entry_column], errors="coerce")
        # A close-time decision is first executable at the next session open.
        data["label_entry_price"] = grouped[entry_column].shift(-1)
        data["label_execution_basis"] = f"next_session_{entry_column}_to_horizon_close"
    else:
        data["label_entry_price"] = data["close"]
        data["label_execution_basis"] = "decision_close_fallback"
    data["stock_future_log_return"] = np.log(data["future_close"] / data["label_entry_price"])

    data["benchmark_future_log_return"] = 0.0
    if benchmark_prices is not None:
        bench_required = {"date", "close"}
        bench_missing = sorted(bench_required - set(benchmark_prices.columns))
        if bench_missing:
            raise ValueError(f"benchmark prices are missing columns: {bench_missing}")
        benchmark_columns = ["date", "close"]
        benchmark_columns.extend(
            column for column in entry_price_columns
            if column in benchmark_prices.columns and column not in benchmark_columns
        )
        benchmark = benchmark_prices.loc[:, benchmark_columns].copy()
        benchmark["date"] = pd.to_datetime(benchmark["date"], errors="coerce")
        benchmark["close"] = pd.to_numeric(benchmark["close"], errors="coerce")
        benchmark = benchmark.dropna().drop_duplicates("date").sort_values("date")
        benchmark_entry_column = next(
            (column for column in entry_price_columns if column in benchmark.columns), ""
        )
        benchmark_entry = (
            pd.to_numeric(benchmark[benchmark_entry_column], errors="coerce").shift(-1)
            if benchmark_entry_column
            else benchmark["close"]
        )
        benchmark["benchmark_future_log_return"] = np.log(
            benchmark["close"].shift(-horizon) / benchmark_entry
        )
        data = data.drop(columns="benchmark_future_log_return").merge(
            benchmark[["date", "benchmark_future_log_return"]], on="date", how="left"
        )
    cost = float(round_trip_cost_rate)
    if cost < 0.0 or cost >= 1.0:
        raise ValueError("round_trip_cost_rate must be in [0, 1)")
    if cost_rate_column in data.columns:
        cost_rate = pd.to_numeric(data[cost_rate_column], errors="coerce").fillna(cost)
    else:
        cost_rate = pd.Series(cost, index=data.index, dtype=float)
    cost_rate = cost_rate.clip(lower=0.0, upper=0.95)
    data["label_round_trip_cost_rate"] = cost_rate
    data["future_excess_log_return_net"] = (
        data["stock_future_log_return"]
        - data["benchmark_future_log_return"]
        + np.log1p(-cost_rate)
    )
    return data


def attach_cross_sectional_relevance(
    frame: pd.DataFrame,
    *,
    label_column: str = "future_excess_log_return_net",
    bins: int = 5,
) -> pd.DataFrame:
    """Convert continuous returns to integer LambdaRank relevance per date."""
    if "date" not in frame or label_column not in frame:
        raise ValueError(f"relevance requires date and {label_column}")
    levels = int(bins)
    if levels < 2:
        raise ValueError("bins must be at least two")
    output = frame.copy()
    percentile = output.groupby("date", sort=False)[label_column].rank(
        pct=True, method="average"
    )
    output["ml_relevance"] = np.floor(percentile * levels).clip(0, levels - 1)
    output.loc[output[label_column].isna(), "ml_relevance"] = np.nan
    return output


def fit_monthly_lgbm_ranker(
    training_frame: pd.DataFrame,
    *,
    feature_columns: Iterable[str],
    as_of_date,
    horizon_days: int,
    validation_date_count: int = 20,
    relevance_bins: int = 5,
    model_params: Mapping[str, object] | None = None,
    model_selection_cost_rate: float = 0.002,
) -> MonthlyRankerArtifact:
    """Fit a real LightGBM LambdaRank model using only matured PIT labels."""
    try:
        from lightgbm import LGBMRanker, early_stopping, record_evaluation
    except ImportError as exc:
        raise RuntimeError("Real lightgbm is required; proxy fallback is forbidden") from exc

    features = tuple(dict.fromkeys(str(column) for column in feature_columns))
    required = {"date", "label_maturity_date", "future_excess_log_return_net", *features}
    missing = sorted(required - set(training_frame.columns))
    if missing:
        raise ValueError(f"monthly ranker training frame is missing columns: {missing}")
    as_of = pd.Timestamp(as_of_date).normalize()
    data = training_frame.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["label_maturity_date"] = pd.to_datetime(data["label_maturity_date"], errors="coerce")
    data["future_excess_log_return_net"] = pd.to_numeric(
        data["future_excess_log_return_net"], errors="coerce"
    )
    data = data[
        data["date"].notna()
        & data["label_maturity_date"].notna()
        & data["label_maturity_date"].le(as_of)
        & data["future_excess_log_return_net"].notna()
    ].copy()
    if data.empty:
        raise ValueError("no matured labels are available at the requested as_of_date")
    data = attach_cross_sectional_relevance(data, bins=relevance_bins)
    unique_dates = pd.Index(sorted(data["date"].dropna().unique()))
    valid_count = int(validation_date_count)
    if valid_count <= 0 or len(unique_dates) <= valid_count + 2:
        raise ValueError("insufficient distinct dates for temporal train/validation split")
    validation_dates = unique_dates[-valid_count:]
    validation_start = pd.Timestamp(validation_dates[0])
    train = data[data["label_maturity_date"].lt(validation_start)].copy()
    valid = data[data["date"].isin(validation_dates)].copy()
    if train.empty or valid.empty:
        raise ValueError("purged temporal split produced an empty train or validation set")
    train = train.sort_values(["date", "symbol"] if "symbol" in train else ["date"])
    valid = valid.sort_values(["date", "symbol"] if "symbol" in valid else ["date"])

    medians: dict[str, float] = {}
    for column in features:
        train[column] = pd.to_numeric(train[column], errors="coerce")
        valid[column] = pd.to_numeric(valid[column], errors="coerce")
        median = float(train[column].median()) if train[column].notna().any() else 0.0
        medians[column] = median
        train[column] = train[column].fillna(median)
        valid[column] = valid[column].fillna(median)
    base_params = {
        "objective": "lambdarank",
        "random_state": 20260717,
        "verbosity": -1,
    }
    if model_params:
        selected_params = dict(model_params)
        parameter_selection_status = "pre_registered_explicit_params"
        nested_candidate_metrics = pd.DataFrame()
    else:
        selected_params, parameter_selection_status, nested_candidate_metrics = _select_nested_lgbm_params(
            train,
            features=features,
            horizon_days=int(horizon_days),
            ranker_class=LGBMRanker,
            early_stopping_callback=early_stopping,
            record_evaluation_callback=record_evaluation,
            cost_rate=float(model_selection_cost_rate),
        )
    nested_iteration_metrics = pd.DataFrame()
    if not nested_candidate_metrics.empty and "iteration_metrics" in nested_candidate_metrics:
        nested_records = []
        for records in nested_candidate_metrics["iteration_metrics"]:
            nested_records.extend(records if isinstance(records, list) else [])
        nested_iteration_metrics = pd.DataFrame(nested_records)
        if not nested_iteration_metrics.empty:
            nested_iteration_metrics["model_month"] = as_of.strftime("%Y-%m")
        nested_candidate_metrics = nested_candidate_metrics.drop(columns="iteration_metrics")
    params = {**base_params, **selected_params}
    if str(params.get("objective")) != "lambdarank":
        raise ValueError("monthly governance ranker objective must remain lambdarank")
    model = LGBMRanker(**params)
    train_group = train.groupby("date", sort=False).size().tolist()
    valid_group = valid.groupby("date", sort=False).size().tolist()
    final_eval_history: dict = {}
    model.fit(
        train.loc[:, features],
        train["ml_relevance"].astype(int),
        group=train_group,
        eval_set=[
            (train.loc[:, features], train["ml_relevance"].astype(int)),
            (valid.loc[:, features], valid["ml_relevance"].astype(int)),
        ],
        eval_names=["train", "outer_valid"],
        eval_group=[train_group, valid_group],
        eval_at=[1, 3, 5],
        callbacks=[record_evaluation(final_eval_history)],
    )
    valid["ml_raw_score"] = model.predict(valid.loc[:, features])
    daily_ic = valid.groupby("date", sort=False).apply(
        lambda group: group["ml_raw_score"].corr(
            group["future_excess_log_return_net"], method="spearman"
        ),
        include_groups=False,
    ).dropna()
    gain = np.asarray(model.booster_.feature_importance(importance_type="gain"), dtype=float)
    gain_share = gain / gain.sum() if gain.sum() > 0.0 else np.zeros(len(features), dtype=float)
    feature_diagnostic_rows = []
    for feature, importance, importance_share in zip(features, gain, gain_share):
        feature_ic = valid.groupby("date", sort=False).apply(
            lambda group: _safe_spearman(
                group[feature], group["future_excess_log_return_net"]
            ),
            include_groups=False,
        ).dropna()
        feature_diagnostic_rows.append({
            "model_month": as_of.strftime("%Y-%m"),
            "trained_as_of": as_of,
            "feature": feature,
            "validation_feature_rank_ic_mean": float(feature_ic.mean()) if not feature_ic.empty else np.nan,
            "validation_feature_rank_ic_positive_share": float((feature_ic > 0).mean()) if not feature_ic.empty else np.nan,
            "gain_importance": float(importance),
            "gain_importance_share": float(importance_share),
            "validation_date_count": int(feature_ic.size),
        })
    flags = []
    if daily_ic.empty:
        flags.append("validation_rank_ic_unavailable")
    elif float(daily_ic.mean()) <= 0.0:
        flags.append("validation_rank_ic_nonpositive")
    score_return_calibration = _fit_score_return_calibration(valid)
    return MonthlyRankerArtifact(
        model=model,
        feature_columns=features,
        feature_medians=medians,
        trained_as_of=as_of,
        model_month=as_of.strftime("%Y-%m"),
        horizon_days=int(horizon_days),
        training_rows=len(train),
        validation_rows=len(valid),
        validation_dates=len(validation_dates),
        validation_rank_ic_mean=float(daily_ic.mean()) if not daily_ic.empty else float("nan"),
        validation_rank_ic_positive_share=float((daily_ic > 0).mean()) if not daily_ic.empty else float("nan"),
        degradation_flags=flags,
        validation_predictions=valid.loc[:, [
            column for column in (
                "date", "symbol", "future_excess_log_return_net",
                "cabinet_native_final_score", "ml_raw_score",
            ) if column in valid.columns
        ]].copy(),
        validation_feature_diagnostics=pd.DataFrame(feature_diagnostic_rows),
        selected_model_params=selected_params,
        parameter_selection_status=parameter_selection_status,
        best_iteration=int(getattr(model, "best_iteration_", 0) or selected_params.get("n_estimators", 0)),
        iteration_metrics=pd.concat([
            nested_iteration_metrics,
            _evaluation_history_frame(
                final_eval_history,
                model_month=as_of.strftime("%Y-%m"),
                stage="outer_locked_audit",
            ),
        ], ignore_index=True),
        nested_candidate_metrics=nested_candidate_metrics,
        score_return_calibration=score_return_calibration,
    )


def _select_nested_lgbm_params(
    train: pd.DataFrame,
    *,
    features,
    horizon_days: int,
    ranker_class,
    early_stopping_callback,
    record_evaluation_callback,
    cost_rate: float,
):
    """Select capacity on an inner purged split; outer validation stays untouched."""
    dates = pd.Index(sorted(train["date"].dropna().unique()))
    inner_valid_days = max(5, min(20, len(dates) // 5))
    if len(dates) <= inner_valid_days + int(horizon_days) + 5:
        return _data_scaled_parameter_candidate(train, features, depth_adjustment=0), "data_scaled_fallback_insufficient_inner_dates", pd.DataFrame()
    inner_dates = dates[-inner_valid_days:]
    inner_start = pd.Timestamp(inner_dates[0])
    inner_train = train[pd.to_datetime(train["label_maturity_date"], errors="coerce").lt(inner_start)].copy()
    inner_valid = train[train["date"].isin(inner_dates)].copy()
    if inner_train.empty or inner_valid.empty:
        return _data_scaled_parameter_candidate(train, features, depth_adjustment=0), "data_scaled_fallback_empty_inner_split", pd.DataFrame()

    rows = []
    candidates = [
        _data_scaled_parameter_candidate(inner_train, features, depth_adjustment=adjustment)
        for adjustment in (-1, 0, 1)
    ]
    unique_candidates = []
    seen = set()
    for candidate in candidates:
        key = tuple(sorted(candidate.items()))
        if key not in seen:
            unique_candidates.append(candidate)
            seen.add(key)
    train_group = inner_train.groupby("date", sort=False).size().tolist()
    valid_group = inner_valid.groupby("date", sort=False).size().tolist()
    for index, candidate in enumerate(unique_candidates):
        model = ranker_class(objective="lambdarank", random_state=20260717, verbosity=-1, **candidate)
        eval_history: dict = {}
        stopping_rounds = max(10, int(np.ceil(np.sqrt(float(candidate["n_estimators"])))))
        model.fit(
            inner_train.loc[:, features], inner_train["ml_relevance"].astype(int), group=train_group,
            eval_set=[
                (inner_train.loc[:, features], inner_train["ml_relevance"].astype(int)),
                (inner_valid.loc[:, features], inner_valid["ml_relevance"].astype(int)),
            ],
            eval_names=["inner_train", "inner_valid"],
            eval_group=[train_group, valid_group], eval_at=[1, 3, 5],
            callbacks=[
                early_stopping_callback(stopping_rounds=stopping_rounds, first_metric_only=True, verbose=False),
                record_evaluation_callback(eval_history),
            ],
        )
        scored = inner_valid[["date", "future_excess_log_return_net"]].copy()
        scored["prediction"] = model.predict(inner_valid.loc[:, features])
        daily_ic = scored.groupby("date", sort=False).apply(
            lambda group: _safe_spearman(group["prediction"], group["future_excess_log_return_net"]),
            include_groups=False,
        ).dropna()
        mean = float(daily_ic.mean()) if not daily_ic.empty else float("-inf")
        se = float(daily_ic.std(ddof=1) / np.sqrt(len(daily_ic))) if len(daily_ic) > 1 else 0.0
        best_iteration = int(getattr(model, "best_iteration_", 0) or candidate["n_estimators"])
        valid_ndcg = eval_history.get("inner_valid", {})
        ndcg5_values = valid_ndcg.get("ndcg@5", valid_ndcg.get("ndcg@3", []))
        ndcg5 = float(ndcg5_values[best_iteration - 1]) if len(ndcg5_values) >= best_iteration else float("nan")
        turnover = _top_k_rank_turnover(scored, prediction_column="prediction", top_k=5)
        instability = float(daily_ic.std(ddof=1)) if len(daily_ic) > 1 else 0.0
        complexity = float(candidate["num_leaves"] * best_iteration * candidate["colsample_bytree"])
        rows.append({
            "candidate_index": index,
            "rank_ic_mean": mean,
            "rank_ic_se": max(se, 0.0),
            "ndcg_at_5": ndcg5,
            "top5_turnover_proxy": turnover,
            "rank_ic_instability": instability,
            "complexity": complexity,
            "configured_iteration_cap": int(candidate["n_estimators"]),
            "best_iteration": best_iteration,
            "stopping_rounds": stopping_rounds,
            "iteration_metrics": _evaluation_history_frame(
                eval_history, model_month="", stage=f"inner_candidate_{index}"
            ).to_dict("records"),
        })
    results = pd.DataFrame(rows).replace([np.inf, -np.inf], np.nan).dropna(subset=["rank_ic_mean", "ndcg_at_5"])
    if results.empty:
        return _data_scaled_parameter_candidate(train, features, depth_adjustment=0), "data_scaled_fallback_inner_ic_unavailable", pd.DataFrame(rows)
    maximum_complexity = max(float(results["complexity"].max()), 1.0)
    results["complexity_normalized"] = results["complexity"] / maximum_complexity
    results["score_mean"] = results.apply(
        lambda row: cost_aware_rank_objective(
            ndcg=float(row["ndcg_at_5"]), turnover=float(row["top5_turnover_proxy"]),
            cost_rate=max(float(cost_rate), 0.0), instability=float(row["rank_ic_instability"]),
            complexity=float(row["complexity_normalized"]), lambda_turnover=1.0,
            lambda_instability=0.10, lambda_complexity=0.01,
        ), axis=1,
    )
    results["score_se"] = results["rank_ic_se"]
    chosen = one_standard_error_choice(results)
    chosen_index = int(chosen["candidate_index"])
    selected = dict(unique_candidates[chosen_index])
    selected["n_estimators"] = int(chosen["best_iteration"])
    results["selected"] = results["candidate_index"].eq(chosen_index)
    return selected, "nested_purged_early_stopped_cost_aware_one_standard_error", results


def _data_scaled_parameter_candidate(train: pd.DataFrame, features, *, depth_adjustment: int) -> dict[str, object]:
    date_count = max(int(pd.Series(train["date"]).nunique()), 1)
    row_count = max(int(len(train)), 1)
    feature_count = max(int(len(features)), 1)
    median_group = max(float(train.groupby("date", sort=False).size().median()), 2.0)
    base_depth = int(np.clip(round(np.log2(np.sqrt(median_group))), 2, 6))
    depth = int(np.clip(base_depth + int(depth_adjustment), 2, 6))
    leaves = int(2 ** depth - 1)
    learning_rate = float(np.clip(1.0 / np.sqrt(date_count), 0.02, 0.10))
    # This is a safety ceiling, not a fitted episode count. Inner validation
    # selects the actual number of boosting rounds by early stopping.
    estimators = int(np.clip(np.ceil(8.0 / learning_rate), 100, 1000))
    minimum_child = int(max(np.ceil(row_count / max(leaves * 8.0, 1.0)), 5))
    column_fraction = float(np.clip(np.sqrt(feature_count) / feature_count, 0.5, 1.0))
    return {
        "n_estimators": estimators,
        "learning_rate": learning_rate,
        "num_leaves": leaves,
        "min_child_samples": minimum_child,
        "subsample": 1.0,
        "colsample_bytree": column_fraction,
        "reg_lambda": float(1.0 / np.sqrt(row_count)),
    }


def _evaluation_history_frame(history: Mapping, *, model_month: str, stage: str) -> pd.DataFrame:
    rows: list[dict] = []
    for dataset, metrics in dict(history or {}).items():
        for metric, values in dict(metrics or {}).items():
            for iteration, value in enumerate(values, start=1):
                rows.append({
                    "model_month": model_month,
                    "stage": stage,
                    "dataset": str(dataset),
                    "metric": str(metric),
                    "boosting_iteration": int(iteration),
                    "value": float(value),
                })
    return pd.DataFrame(rows)


def _top_k_rank_turnover(frame: pd.DataFrame, *, prediction_column: str, top_k: int) -> float:
    previous: set[str] | None = None
    changes: list[float] = []
    symbol_column = "symbol" if "symbol" in frame.columns else None
    for _, group in frame.groupby("date", sort=True):
        ranked = group.nlargest(min(int(top_k), len(group)), prediction_column)
        current = set(ranked[symbol_column].astype(str)) if symbol_column else set(ranked.index.astype(str))
        if previous is not None:
            denominator = max(min(len(previous), len(current)), 1)
            changes.append(1.0 - len(previous & current) / denominator)
        previous = current
    return float(np.mean(changes)) if changes else 0.0


def predict_daily_rank(
    artifact: MonthlyRankerArtifact,
    candidates: pd.DataFrame,
) -> pd.DataFrame:
    """Attach raw and within-day percentile ML scores without making decisions."""
    missing = sorted(set(artifact.feature_columns) - set(candidates.columns))
    # Cabinet-family columns are cross-sectionally dynamic: a family can be
    # present during training but have no eligible proposal on a later day. In
    # that case the whole column is absent rather than merely null. Align those
    # columns to the locked training schema and let the persisted training
    # median provide the same treatment used for NaNs. Fixed/base feature loss
    # remains a hard contract error.
    missing_dynamic = [
        column for column in missing
        if column.startswith("cabinet_family_") and column.endswith("_score")
    ]
    missing_fixed = sorted(set(missing) - set(missing_dynamic))
    if missing_fixed:
        raise ValueError(f"candidate frame is missing trained ML features: {missing_fixed}")
    output = candidates.copy()
    matrix = pd.DataFrame(index=output.index)
    for column in artifact.feature_columns:
        source = (
            output[column]
            if column in output.columns
            else pd.Series(float("nan"), index=output.index, dtype=float)
        )
        matrix[column] = pd.to_numeric(source, errors="coerce").fillna(
            artifact.feature_medians[column]
        )
    output["monthly_lgbm_raw_score"] = artifact.model.predict(matrix.loc[:, artifact.feature_columns])
    if "date" in output:
        output["monthly_lgbm_rank_percentile"] = output.groupby("date", sort=False)[
            "monthly_lgbm_raw_score"
        ].rank(pct=True, method="average")
    else:
        output["monthly_lgbm_rank_percentile"] = output["monthly_lgbm_raw_score"].rank(
            pct=True, method="average"
        )
    output["monthly_lgbm_model_month"] = artifact.model_month
    output["monthly_lgbm_trained_as_of"] = artifact.trained_as_of
    output["monthly_lgbm_runtime_model"] = artifact.runtime_model
    output["monthly_lgbm_schema_imputed_feature_count"] = len(missing_dynamic)
    output["monthly_lgbm_schema_imputed_features"] = "|".join(missing_dynamic)
    if not artifact.score_return_calibration.empty:
        calibration = artifact.score_return_calibration.set_index("rank_bin")
        bins = np.floor(output["monthly_lgbm_rank_percentile"].clip(0.0, 0.999999) * len(calibration)).astype(int)
        output[f"expected_edge_{artifact.horizon_days}d"] = bins.map(calibration["expected_net_alpha"])
        output[f"conservative_expected_edge_{artifact.horizon_days}d"] = bins.map(calibration["conservative_net_alpha"])
        output[f"expected_edge_{artifact.horizon_days}d_source"] = "locked_validation_rank_bin_calibration"
    return output


def _fit_score_return_calibration(valid: pd.DataFrame, bins: int = 5) -> pd.DataFrame:
    """Map ordinal rank scores to auditable return units using locked validation only."""
    data = valid[["date", "ml_raw_score", "future_excess_log_return_net"]].copy()
    data["rank_percentile"] = data.groupby("date", sort=False)["ml_raw_score"].rank(pct=True, method="average")
    levels = max(min(int(bins), int(data.groupby("date").size().median())), 2)
    data["rank_bin"] = np.floor(data["rank_percentile"].clip(0.0, 0.999999) * levels).astype(int)
    rows = []
    for rank_bin, group in data.groupby("rank_bin", sort=True):
        daily = group.groupby("date", sort=False)["future_excess_log_return_net"].mean().dropna()
        mean = float(daily.mean()) if not daily.empty else float("nan")
        se = float(daily.std(ddof=1) / np.sqrt(len(daily))) if len(daily) > 1 else float("inf")
        rows.append({"rank_bin": int(rank_bin), "raw_expected_net_alpha": mean, "standard_error": se, "date_count": len(daily)})
    result = pd.DataFrame(rows).sort_values("rank_bin")
    if result.empty:
        return result
    # Enforce the ranker's declared direction without inventing scale.
    result["expected_net_alpha"] = result["raw_expected_net_alpha"].cummax()
    result["conservative_net_alpha"] = result["expected_net_alpha"] - 1.2815515655446004 * result["standard_error"]
    return result


def _safe_spearman(left: pd.Series, right: pd.Series) -> float:
    pair = pd.DataFrame({"left": left, "right": right}).dropna()
    if len(pair) < 3 or pair["left"].nunique() < 2 or pair["right"].nunique() < 2:
        return float("nan")
    return float(pair["left"].corr(pair["right"], method="spearman"))


def calibrate_fusion_weight(
    validation_frame: pd.DataFrame,
    *,
    rule_score_column: str,
    ml_score_column: str,
    label_column: str = "future_excess_log_return_net",
    maximum_ml_weight: float,
    horizon_days: int = 5,
) -> FusionCalibration:
    """Calibrate ML weight from an untouched temporal validation window.

    Let ``R``, ``M`` and ``Y`` be daily cross-sectional percentiles for the
    rule score, ML score and realized label.  The unconstrained least-squares
    solution for ``H = R + w(M-R)`` is::

        w* = Cov(Y-R, M-R) / Var(M-R)

    It is clipped to the pre-registered ML ceiling and shrunk by validation IC
    reliability ``max(IC, 0) / (abs(IC) + SE(IC))``.  Non-positive validation
    IC therefore gives exactly zero ML authority.
    """
    ceiling = float(maximum_ml_weight)
    if not 0.0 <= ceiling <= 1.0:
        raise ValueError("maximum_ml_weight must be pre-registered in [0, 1]")
    required = {"date", rule_score_column, ml_score_column, label_column}
    missing = sorted(required - set(validation_frame.columns))
    if missing:
        raise ValueError(f"fusion validation frame is missing columns: {missing}")
    data = validation_frame.loc[:, list(required)].copy()
    for column in (rule_score_column, ml_score_column, label_column):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna()
    if data.empty:
        return _fallback_fusion(ceiling, "fallback_no_validation_rows")
    for source, target in (
        (rule_score_column, "rule_rank"),
        (ml_score_column, "ml_rank"),
        (label_column, "realized_rank"),
    ):
        data[target] = data.groupby("date", sort=False)[source].rank(pct=True, method="average")
    # Ranking remains the model objective, but trading authority must be
    # measured in the original cost-after excess-return unit.
    data["realized_net_alpha"] = data[label_column]
    difference = data["ml_rank"] - data["rule_rank"]
    target_residual = data["realized_rank"] - data["rule_rank"]
    # Give each validation date equal authority even when candidate counts vary.
    date_size = data.groupby("date", sort=False)["date"].transform("size").clip(lower=1)
    row_weight = 1.0 / date_size
    denominator = float(np.dot(row_weight * difference, difference))
    if not np.isfinite(denominator) or denominator <= 1e-12:
        return _fallback_fusion(ceiling, "fallback_rule_ml_collinear")
    raw_weight = float(np.dot(row_weight * target_residual, difference) / denominator)
    daily_ic = data.groupby("date", sort=False).apply(
        lambda group: group["ml_rank"].corr(group["realized_rank"], method="spearman"),
        include_groups=False,
    ).dropna()
    if daily_ic.empty:
        return _fallback_fusion(ceiling, "fallback_validation_ic_unavailable", raw_weight)
    ic_mean = float(daily_ic.mean())
    ic_se = float(daily_ic.std(ddof=1) / np.sqrt(len(daily_ic))) if len(daily_ic) > 1 else float("inf")
    if not np.isfinite(ic_mean) or ic_mean <= 0.0:
        return FusionCalibration(0.0, raw_weight, 0.0, ceiling, ic_mean, ic_se, "fallback_validation_ic_nonpositive")
    if float((daily_ic > 0.0).mean()) < 0.50:
        return FusionCalibration(0.0, raw_weight, 0.0, ceiling, ic_mean, ic_se, "fallback_validation_ic_sign_unstable")
    reliability = ic_mean / (abs(ic_mean) + max(ic_se, 0.0)) if np.isfinite(ic_se) else 0.0
    weight = float(np.clip(raw_weight, 0.0, ceiling)) * float(np.clip(reliability, 0.0, 1.0))
    if weight > 0.0:
        treatment = _validation_top_k_treatment(data, weight=weight, top_k=5)
        if len(treatment) < 5:
            return FusionCalibration(0.0, raw_weight, reliability, ceiling, ic_mean, ic_se, "fallback_treatment_sample_insufficient")
        treatment_mean = float(treatment.mean())
        treatment_se = _hac_standard_error(
            treatment,
            max_lag=min(max(int(horizon_days) - 1, 1), len(treatment) - 1),
        )
        treatment_lcb = treatment_mean - 1.2815515655446004 * treatment_se
        if not np.isfinite(treatment_lcb) or treatment_lcb <= 0.0:
            return FusionCalibration(0.0, raw_weight, reliability, ceiling, ic_mean, ic_se, "fallback_treatment_lcb_nonpositive")
        status = "active_treatment_lcb_positive"
    else:
        status = "fallback_nonpositive_optimal_weight"
    return FusionCalibration(weight, raw_weight, reliability, ceiling, ic_mean, ic_se, status)


def _validation_top_k_treatment(data: pd.DataFrame, *, weight: float, top_k: int) -> pd.Series:
    work = data.copy()
    work["hybrid_rank"] = (1.0 - float(weight)) * work["rule_rank"] + float(weight) * work["ml_rank"]
    rows = []
    for _, group in work.groupby("date", sort=True):
        k = min(max(int(top_k), 1), len(group))
        rule = group.nlargest(k, "rule_rank")["realized_net_alpha"].mean()
        hybrid = group.nlargest(k, "hybrid_rank")["realized_net_alpha"].mean()
        rows.append(float(hybrid - rule))
    return pd.Series(rows, dtype=float)


def _hac_standard_error(values: pd.Series, *, max_lag: int) -> float:
    x = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    n = len(x)
    if n < 2:
        return float("inf")
    centered = x - x.mean()
    long_run_variance = float(centered @ centered / n)
    for lag in range(1, min(int(max_lag), n - 1) + 1):
        weight = 1.0 - lag / (min(int(max_lag), n - 1) + 1.0)
        gamma = float(centered[lag:] @ centered[:-lag] / n)
        long_run_variance += 2.0 * weight * gamma
    return float(np.sqrt(max(long_run_variance, 0.0) / n))


def _fallback_fusion(
    ceiling: float,
    status: str,
    raw_weight: float = float("nan"),
) -> FusionCalibration:
    return FusionCalibration(
        ml_weight=0.0,
        unconstrained_weight=float(raw_weight),
        reliability=0.0,
        maximum_ml_weight=float(ceiling),
        validation_rank_ic_mean=float("nan"),
        validation_rank_ic_standard_error=float("nan"),
        status=status,
    )


def apply_continuous_rank_fusion(
    candidates: pd.DataFrame,
    calibration: FusionCalibration,
    *,
    rule_score_column: str = "cabinet_native_final_score",
    ml_score_column: str = "monthly_lgbm_raw_score",
) -> pd.DataFrame:
    """Apply H=(1-lambda)rank(rule)+lambda*rank(ML), without hard vetoes."""
    required = {rule_score_column}
    if calibration.ml_weight > 0.0:
        required.add(ml_score_column)
    missing = sorted(required - set(candidates.columns))
    if missing:
        raise ValueError(f"hybrid candidates are missing score columns: {missing}")
    output = candidates.copy()
    groups = output.groupby("date", sort=False) if "date" in output else None
    rule = pd.to_numeric(output[rule_score_column], errors="coerce")
    rule_rank = groups[rule_score_column].rank(pct=True, method="average") if groups is not None else rule.rank(pct=True, method="average")
    if calibration.ml_weight > 0.0:
        ml = pd.to_numeric(output[ml_score_column], errors="coerce")
        if groups is not None:
            # Rank the numeric temporary series to avoid object/string ordering.
            ml_rank = ml.groupby(output["date"], sort=False).rank(pct=True, method="average")
        else:
            ml_rank = ml.rank(pct=True, method="average")
        ml_rank = ml_rank.fillna(rule_rank)
    else:
        ml_rank = rule_rank.copy()
    weight = float(calibration.ml_weight)
    output["hybrid_rule_rank_percentile"] = rule_rank
    output["hybrid_ml_rank_percentile"] = ml_rank
    output["hybrid_ml_weight"] = weight
    output["hybrid_rule_weight"] = 1.0 - weight
    output["hybrid_final_score"] = (1.0 - weight) * rule_rank + weight * ml_rank
    output["hybrid_fusion_status"] = calibration.status
    output["hybrid_fusion_formula_version"] = calibration.formula_version
    output["hybrid_score_authority"] = "continuous_rank_adjustment_only"
    return output


def feature_contract_table() -> pd.DataFrame:
    rows = []
    for spec in (*HYBRID_FEATURE_SPECS, *PENDING_FEATURE_SPECS):
        rows.append(
            {
                "feature": spec.name,
                "source_columns": "|".join(spec.source_columns),
                "family": spec.family,
                "status": spec.status,
                "pit_requirement": spec.pit_requirement,
            }
        )
    return pd.DataFrame(rows)


class OnlineMonthlyLGBMController:
    """PIT candidate-history controller: train monthly, predict daily."""

    BASE_FEATURES = (
        "cabinet_strict_entry_score", "cabinet_proxy_entry_score",
        "cabinet_timing_score", "cabinet_risk_safety_score",
        "cabinet_liquidity_health_score",
        "cabinet_hold_support_score",
        "ret_5", "ret_20", "volatility_20", "amount_to_ma20",
        "close_to_ma20", "orderflow_candidate_score",
        "flow_close_location_value", "flow_accumulation_proxy", "flow_distribution_proxy",
    )

    PIT_RESTRICTED_FAMILY_TOKENS = (
        "value", "valuation", "profitability", "quality", "investment",
        "cashflow", "growth", "event",
    )

    def __init__(
        self,
        *,
        maximum_ml_weight: float,
        benchmark_symbol: str,
        horizon_days: int = 5,
        validation_date_count: int = 20,
        minimum_training_date_count: int = 45,
        round_trip_cost_rate: float,
        allow_pit_restricted_features: bool = False,
        impact_coefficient: float = 0.10,
        model_params: Mapping[str, object] | None = None,
        treatment_top_k: int = 5,
        include_hold_support: bool = False,
    ):
        if not 0.0 <= float(maximum_ml_weight) <= 1.0:
            raise ValueError("maximum_ml_weight must be in [0, 1]")
        if int(minimum_training_date_count) <= int(validation_date_count) + int(horizon_days):
            raise ValueError("minimum_training_date_count must exceed validation plus label horizon")
        self.maximum_ml_weight = float(maximum_ml_weight)
        self.benchmark_symbol = str(benchmark_symbol)
        self.horizon_days = int(horizon_days)
        self.validation_date_count = int(validation_date_count)
        self.minimum_training_date_count = int(minimum_training_date_count)
        self.round_trip_cost_rate = float(round_trip_cost_rate)
        self.allow_pit_restricted_features = bool(allow_pit_restricted_features)
        self.impact_coefficient = max(float(impact_coefficient), 0.0)
        self.model_params = dict(model_params or {})
        self.treatment_top_k = max(int(treatment_top_k), 1)
        self.include_hold_support = bool(include_hold_support)
        self.history_frames: list[pd.DataFrame] = []
        self.artifact: MonthlyRankerArtifact | None = None
        self.calibration: FusionCalibration | None = None
        self.last_training_month = ""
        self.training_attempt_rows: list[dict] = []
        self.feature_diagnostic_rows: list[dict] = []
        self.iteration_metric_rows: list[dict] = []
        self.nested_candidate_rows: list[dict] = []
        self.treatment_candidate_rows: list[dict] = []
        self.treatment_daily_rows: list[dict] = []

    def process_day(
        self,
        candidates: pd.DataFrame,
        *,
        as_of_date,
        price_history: pd.DataFrame,
    ) -> tuple[pd.DataFrame, dict]:
        as_of = pd.Timestamp(as_of_date).normalize()
        month = as_of.strftime("%Y-%m")
        if month != self.last_training_month:
            self._train_as_of(as_of, price_history)
            self.last_training_month = month
        if self.artifact is not None and self.calibration is not None:
            prepared = self._prepare_features(candidates)
            scored = predict_daily_rank(self.artifact, prepared)
            fused = apply_continuous_rank_fusion(scored, self.calibration)
        else:
            fallback = FusionCalibration(
                0.0, float("nan"), 0.0, self.maximum_ml_weight,
                float("nan"), float("nan"), "fallback_insufficient_matured_history",
            )
            fused = apply_continuous_rank_fusion(candidates, fallback)
        fused = attach_rank_treatment(fused, top_k=self.treatment_top_k)
        treatment_columns = [
            column for column in (
                "date", "symbol", "ml_rule_rank", "ml_hybrid_rank", "ml_rank_improvement",
                "ml_rule_top_k", "ml_hybrid_top_k", "ml_treatment_group",
                "monthly_lgbm_rank_percentile", "hybrid_final_score",
            ) if column in fused.columns
        ]
        ledger = fused.loc[:, treatment_columns].copy()
        ledger["date"] = as_of
        self.treatment_candidate_rows.extend(ledger.to_dict("records"))
        self.treatment_daily_rows.extend(
            daily_treatment_summary(ledger, top_k=self.treatment_top_k).to_dict("records")
        )
        self._observe(candidates, as_of)
        audit = {
            "date": as_of,
            "model_available": self.artifact is not None,
            **(
                self.calibration.audit_dict()
                if self.calibration is not None
                else FusionCalibration(
                    0.0, float("nan"), 0.0, self.maximum_ml_weight,
                    float("nan"), float("nan"), "fallback_insufficient_matured_history",
                ).audit_dict()
            ),
        }
        if self.artifact is not None:
            audit.update(self.artifact.audit_dict())
        return fused, audit

    def _observe(self, candidates: pd.DataFrame, as_of: pd.Timestamp) -> None:
        if candidates is None or candidates.empty:
            return
        prepared = self._prepare_features(candidates)
        columns = ["date", "symbol", "cabinet_native_final_score", *self._available_feature_columns(prepared)]
        snapshot = prepared.loc[:, list(dict.fromkeys(column for column in columns if column in prepared))].copy()
        snapshot["date"] = as_of
        self.history_frames.append(snapshot)

    def _train_as_of(self, as_of: pd.Timestamp, price_history: pd.DataFrame) -> None:
        unique_history_dates = len({pd.Timestamp(frame["date"].iloc[0]) for frame in self.history_frames if not frame.empty})
        attempt = {"training_month": as_of.strftime("%Y-%m"), "as_of": as_of, "history_dates": unique_history_dates}
        if unique_history_dates < self.minimum_training_date_count:
            attempt["status"] = "insufficient_history_dates"
            self.training_attempt_rows.append(attempt)
            return
        history = pd.concat(self.history_frames, ignore_index=True)
        feature_columns = self._available_feature_columns(history)
        if len(feature_columns) < 6:
            attempt["status"] = "insufficient_feature_contract"
            self.training_attempt_rows.append(attempt)
            return
        prices = price_history.copy()
        prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
        prices = prices[prices["date"].le(as_of)]
        prices = self._attach_execution_cost_estimate(prices)
        benchmark_columns = [
            column for column in ("date", "close", "open_nominal", "open")
            if column in prices.columns
        ]
        benchmark = prices[prices["symbol"].astype(str).eq(self.benchmark_symbol)][benchmark_columns].copy()
        stock_prices = prices[~prices["symbol"].astype(str).eq(self.benchmark_symbol)]
        if benchmark.empty:
            attempt["status"] = "benchmark_unavailable"
            self.training_attempt_rows.append(attempt)
            return
        labels = build_excess_return_labels(
            stock_prices,
            horizon_days=self.horizon_days,
            benchmark_prices=benchmark,
            round_trip_cost_rate=self.round_trip_cost_rate,
        )
        train_frame = history.merge(
            labels[["date", "symbol", "label_maturity_date", "future_excess_log_return_net"]],
            on=["date", "symbol"], how="inner",
        )
        try:
            artifact = fit_monthly_lgbm_ranker(
                train_frame,
                feature_columns=feature_columns,
                as_of_date=as_of,
                horizon_days=self.horizon_days,
                validation_date_count=self.validation_date_count,
                model_params=self.model_params,
                model_selection_cost_rate=self.round_trip_cost_rate,
            )
            validation = artifact.validation_predictions
            calibration = calibrate_fusion_weight(
                validation,
                rule_score_column="cabinet_native_final_score",
                ml_score_column="ml_raw_score",
                maximum_ml_weight=self.maximum_ml_weight,
                horizon_days=self.horizon_days,
            )
        except (ValueError, RuntimeError) as exc:
            attempt["status"] = f"training_failed:{type(exc).__name__}"
            self.training_attempt_rows.append(attempt)
            return
        self.artifact = artifact
        self.calibration = calibration
        if not artifact.validation_feature_diagnostics.empty:
            diagnostic = artifact.validation_feature_diagnostics.copy()
            diagnostic["ml_weight"] = float(calibration.ml_weight)
            diagnostic["calibration_status"] = str(calibration.status)
            self.feature_diagnostic_rows.extend(diagnostic.to_dict("records"))
        if not artifact.iteration_metrics.empty:
            metrics = artifact.iteration_metrics.copy()
            metrics["training_month"] = as_of.strftime("%Y-%m")
            self.iteration_metric_rows.extend(metrics.to_dict("records"))
        if not artifact.nested_candidate_metrics.empty:
            candidates = artifact.nested_candidate_metrics.copy()
            candidates["training_month"] = as_of.strftime("%Y-%m")
            candidates["trained_as_of"] = as_of
            self.nested_candidate_rows.extend(candidates.to_dict("records"))
        attempt.update({"status": calibration.status, **artifact.audit_dict(), **calibration.audit_dict()})
        self.training_attempt_rows.append(attempt)

    @classmethod
    def _prepare_features(cls, frame: pd.DataFrame) -> pd.DataFrame:
        output = frame.copy()
        if "amount_to_ma20" not in output and {"amount", "amount_ma20"}.issubset(output.columns):
            denominator = pd.to_numeric(output["amount_ma20"], errors="coerce").replace(0.0, np.nan)
            output["amount_to_ma20"] = pd.to_numeric(output["amount"], errors="coerce") / denominator
        if "close_to_ma20" not in output and {"close", "ma_20"}.issubset(output.columns):
            denominator = pd.to_numeric(output["ma_20"], errors="coerce").replace(0.0, np.nan)
            output["close_to_ma20"] = pd.to_numeric(output["close"], errors="coerce") / denominator - 1.0
        return output

    @classmethod
    def _base_available_feature_columns(cls, frame: pd.DataFrame) -> tuple[str, ...]:
        family = sorted(
            column for column in frame.columns
            if column.startswith("cabinet_family_") and column.endswith("_score")
        )
        return tuple(column for column in (*cls.BASE_FEATURES, *family) if column in frame.columns)

    def _available_feature_columns(self, frame: pd.DataFrame) -> tuple[str, ...]:
        columns = self._base_available_feature_columns(frame)
        if not self.include_hold_support:
            columns = tuple(column for column in columns if column != "cabinet_hold_support_score")
        if self.allow_pit_restricted_features:
            return pit_eligible_features(frame, columns)
        return tuple(
            column for column in columns
            if not (
                column.startswith("cabinet_family_")
                and any(token in column.lower() for token in self.PIT_RESTRICTED_FAMILY_TOKENS)
            )
        )

    def _attach_execution_cost_estimate(self, prices: pd.DataFrame) -> pd.DataFrame:
        output = prices.copy()
        base = float(self.round_trip_cost_rate)
        close = pd.to_numeric(
            output.get("close_nominal", output.get("close", pd.Series(float("nan"), index=output.index))),
            errors="coerce",
        )
        amount = pd.to_numeric(output.get("amount", pd.Series(float("nan"), index=output.index)), errors="coerce")
        volatility = pd.to_numeric(output.get("volatility_20", pd.Series(0.0, index=output.index)), errors="coerce").fillna(0.0).clip(lower=0.0)
        participation = ((close * 100.0) / amount.replace(0.0, np.nan)).clip(lower=0.0)
        impact = self.impact_coefficient * volatility * np.sqrt(participation)
        output["estimated_round_trip_cost_rate"] = (base + impact.fillna(0.0)).clip(0.0, 0.95)
        return output

    def training_attempt_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.training_attempt_rows)

    def feature_diagnostic_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.feature_diagnostic_rows)

    def iteration_metric_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.iteration_metric_rows)

    def nested_candidate_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.nested_candidate_rows)

    def treatment_candidate_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.treatment_candidate_rows)

    def treatment_daily_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.treatment_daily_rows)

    def treatment_effect_frame(self, price_history: pd.DataFrame) -> pd.DataFrame:
        ledger = self.treatment_candidate_frame()
        if ledger.empty:
            return pd.DataFrame()
        prices = self._attach_execution_cost_estimate(price_history.copy())
        benchmark_columns = [
            column for column in ("date", "close", "open_nominal", "open") if column in prices.columns
        ]
        benchmark = prices[prices["symbol"].astype(str).eq(self.benchmark_symbol)][benchmark_columns]
        stocks = prices[~prices["symbol"].astype(str).eq(self.benchmark_symbol)]
        if benchmark.empty or stocks.empty:
            return pd.DataFrame()
        labels = build_excess_return_labels(
            stocks,
            horizon_days=self.horizon_days,
            benchmark_prices=benchmark,
            round_trip_cost_rate=self.round_trip_cost_rate,
        )
        return mature_treatment_effect(ledger, labels)
