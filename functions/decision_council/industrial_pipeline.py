"""Serial P2-P7 governance build pipeline for an exploratory research workstation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    DECISION_COUNCIL_VERSION,
    FEATURE_DAILY_PARQUET,
    GOVERNANCE_BANDIT_ACTION_BOUND_RATIO,
    GOVERNANCE_BANDIT_ACTIONS_CSV,
    GOVERNANCE_BANDIT_SHADOW_DAYS,
    GOVERNANCE_DEFAULT_TOP_N,
    GOVERNANCE_DEFAULT_TURNOVER_BUDGET,
    GOVERNANCE_HOLD_RANK_LIMIT,
    GOVERNANCE_INDUSTRIAL_DIR,
    GOVERNANCE_INDUSTRIAL_MANIFEST_JSON,
    GOVERNANCE_INITIAL_TRANSITION_DAYS,
    GOVERNANCE_MODEL_CONGRESS_CSV,
    GOVERNANCE_MODEL_REGISTRY_JSON,
    GOVERNANCE_MONITORING_POLICY_JSON,
    GOVERNANCE_MOMENTUM_REBOUND_DRAWDOWN,
    GOVERNANCE_MOMENTUM_REBOUND_RETURN,
    GOVERNANCE_PHASE_GATE_CSV,
    GOVERNANCE_RESEARCH_REFERENCES_CSV,
    GOVERNANCE_SAFETY_CALIBRATION_CSV,
    GOVERNANCE_SAFETY_DAILY_CSV,
    GOVERNANCE_SAFETY_EVALUATION_CSV,
    GOVERNANCE_SAFETY_L2,
    GOVERNANCE_SAFETY_LEARNING_RATE,
    GOVERNANCE_SAFETY_MAX_ITERATIONS,
    GOVERNANCE_SAFETY_MODEL_JSON,
    GOVERNANCE_SAFETY_TRAIN_RATIO,
    GOVERNANCE_SAFETY_VALIDATION_RATIO,
    GOVERNANCE_STREAM_BATCH_SIZE,
    GOVERNANCE_TRAIN_EMBARGO_PERIODS,
    GOVERNANCE_TRAIN_PURGE_PERIODS,
    GOVERNANCE_TRANSITION_PROTOCOL_JSON,
)
from functions.decision_council.advanced_policies import (
    BanditAction,
    fit_isotonic_calibration_table,
    validate_bandit_actions,
)
from functions.pipeline_cache import code_file_fingerprint, file_fingerprint


SAFETY_FEATURES = [
    "market_return_1d",
    "market_return_5d",
    "market_return_20d",
    "market_volatility_20d",
    "market_liquidity_stress_ratio",
    "momentum_rebound_regime",
]


@dataclass(frozen=True)
class SafetyCostMatrix:
    false_positive_cost: float
    false_negative_cost: float
    true_positive_cost: float = 0.0
    true_negative_cost: float = 0.0
    method: str = "median_crash_drawdown_divided_by_median_normal_volatility"


def run_industrial_governance_build(
    *,
    feature_path=FEATURE_DAILY_PARQUET,
    output_dir=GOVERNANCE_INDUSTRIAL_DIR,
    batch_size: int = GOVERNANCE_STREAM_BATCH_SIZE,
) -> dict[str, Path]:
    """Build all P2-P7 contracts serially without activating unvalidated models."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    saved = {}
    congress = build_model_congress_catalog()
    saved["model_congress_catalog"] = _write_csv(congress, output / GOVERNANCE_MODEL_CONGRESS_CSV.name)
    daily = stream_market_safety_dataset(feature_path, batch_size=batch_size)
    saved["safety_daily_dataset"] = _write_csv(daily, output / GOVERNANCE_SAFETY_DAILY_CSV.name)
    training = fit_serial_safety_model(daily)
    saved["safety_model"] = _write_json(training["model"], output / GOVERNANCE_SAFETY_MODEL_JSON.name)
    saved["safety_calibration"] = _write_csv(training["calibration"], output / GOVERNANCE_SAFETY_CALIBRATION_CSV.name)
    saved["safety_evaluation"] = _write_csv(training["evaluation"], output / GOVERNANCE_SAFETY_EVALUATION_CSV.name)
    actions = build_bounded_bandit_actions()
    saved["bandit_action_contract"] = _write_csv(actions, output / GOVERNANCE_BANDIT_ACTIONS_CSV.name)
    saved["transition_protocol"] = _write_json(build_initial_transition_protocol(), output / GOVERNANCE_TRANSITION_PROTOCOL_JSON.name)
    saved["monitoring_policy"] = _write_json(build_monitoring_rollback_policy(), output / GOVERNANCE_MONITORING_POLICY_JSON.name)
    saved["research_references"] = _write_csv(build_research_reference_catalog(), output / GOVERNANCE_RESEARCH_REFERENCES_CSV.name)
    registry = build_local_model_registry(congress, training, actions)
    saved["model_registry"] = _write_json(registry, output / GOVERNANCE_MODEL_REGISTRY_JSON.name)
    gates = build_phase_gate_report(training, registry)
    saved["phase_gate_report"] = _write_csv(gates, output / GOVERNANCE_PHASE_GATE_CSV.name)
    manifest = build_industrial_manifest(feature_path, saved, training)
    saved["industrial_manifest"] = _write_json(manifest, output / GOVERNANCE_INDUSTRIAL_MANIFEST_JSON.name)
    return saved


def build_model_congress_catalog() -> pd.DataFrame:
    """Declare voter roles explicitly; catalog entries are not automatic champions."""
    rows = [
        ("lower_house", "momentum_20", "rule_alpha", "ret_20", "candidate", "momentum_rebound_regime may mute"),
        ("lower_house", "mom_lowvol", "rule_alpha", "score_mom_lowvol", "candidate", "liquidity-screened shadow only"),
        ("lower_house", "ma_break", "rule_alpha", "close_to_ma20", "candidate", "liquidity-screened shadow only"),
        ("lower_house", "ml_elasticnet", "ml_alpha", "score_ml", "candidate", "OOF score required"),
        ("lower_house", "ml_xgboost", "ml_alpha", "score_ml", "candidate", "OOF score required"),
        ("lower_house", "ml_lightgbm", "ml_alpha", "score_ml", "candidate", "OOF score and early stopping required"),
        ("lower_house", "low_vol", "conservative_alpha", "volatility_20", "candidate", "ascending rank"),
        ("lower_house", "volume_extreme", "aggressive_alpha", "volume_ma_20", "candidate", "impact sensitivity required"),
        ("lower_house", "kline_shape", "shape_alpha", "amplitude", "candidate", "shadow only"),
        ("senate", "portfolio_construction_committee", "risk_allocator", "inverse_volatility_caps", "active_rule", "Ledoit-Wolf upgrade pending"),
        ("safety_council", "calibrated_crash_probability", "risk_veto", "daily_market_state", "candidate", "cannot activate before calibration gate"),
        ("president", "rules_based_president", "policy", "frozen_rule_parameters", "active_rule", "baseline champion"),
        ("president", "bounded_linucb", "policy", "finite_actions", "shadow_only", "252 shadow days before admission"),
    ]
    return pd.DataFrame(rows, columns=["institution", "model_name", "model_family", "signal_source", "registry_stage", "admission_note"])


def stream_market_safety_dataset(feature_path, *, batch_size=GOVERNANCE_STREAM_BATCH_SIZE) -> pd.DataFrame:
    """Aggregate market safety features in Arrow batches to bound peak memory."""
    import pyarrow.parquet as pq

    available = set(pq.read_schema(feature_path).names)
    desired = [
        "date",
        "symbol",
        "instrument_type",
        "close_nominal",
        "close",
        "amount",
        "amount_ma20",
        "volatility_20",
        "is_trading",
    ]
    columns = [column for column in desired if column in available]
    required = {"date", "symbol", "instrument_type", "amount"}
    missing = sorted(required - set(columns))
    if missing:
        raise ValueError(f"Safety aggregation missing feature columns: {missing}")
    parts = []
    parquet = pq.ParquetFile(feature_path)
    for batch in parquet.iter_batches(batch_size=int(batch_size), columns=columns):
        part = batch.to_pandas()
        part["date"] = pd.to_datetime(part["date"], errors="coerce")
        part = part[part["instrument_type"].astype(str).isin(["stock", "etf_fund"])]
        if "is_trading" in part.columns:
            part = part[part["is_trading"].fillna(False)]
        part["amount"] = pd.to_numeric(part["amount"], errors="coerce").fillna(0.0)
        amount_ma20 = pd.to_numeric(part.get("amount_ma20", part["amount"]), errors="coerce").fillna(part["amount"])
        part["liquidity_stressed"] = part["amount"] < amount_ma20 * 0.5
        part["volatility_20"] = pd.to_numeric(part.get("volatility_20", 0.0), errors="coerce")
        parts.append(
            part.groupby("date", as_index=False).agg(
                eligible_instruments=("symbol", "size"),
                stressed_instruments=("liquidity_stressed", "sum"),
                market_volatility_sum=("volatility_20", "sum"),
                market_volatility_count=("volatility_20", "count"),
                market_total_amount=("amount", "sum"),
            )
        )
    if not parts:
        raise ValueError("Feature parquet did not yield safety rows")
    aggregated = pd.concat(parts, ignore_index=True).groupby("date", as_index=False).agg(
        eligible_instruments=("eligible_instruments", "sum"),
        stressed_instruments=("stressed_instruments", "sum"),
        market_volatility_sum=("market_volatility_sum", "sum"),
        market_volatility_count=("market_volatility_count", "sum"),
        market_total_amount=("market_total_amount", "sum"),
    )
    aggregated["market_liquidity_stress_ratio"] = (
        aggregated["stressed_instruments"] / aggregated["eligible_instruments"].clip(lower=1)
    )
    aggregated["market_volatility_20d"] = (
        aggregated["market_volatility_sum"] / aggregated["market_volatility_count"].clip(lower=1)
    )
    aggregated = aggregated.drop(columns=["market_volatility_sum", "market_volatility_count"])
    market_close = _stream_market_proxy_close(feature_path, columns=columns, batch_size=batch_size)
    data = aggregated.merge(market_close, on="date", how="left").sort_values("date").reset_index(drop=True)
    data["market_return_1d"] = data["market_proxy_close"].pct_change(fill_method=None)
    data["market_return_5d"] = data["market_proxy_close"].pct_change(5, fill_method=None)
    data["market_return_20d"] = data["market_proxy_close"].pct_change(20, fill_method=None)
    data["momentum_rebound_regime"] = (
        (data["market_return_20d"].shift(5) <= GOVERNANCE_MOMENTUM_REBOUND_DRAWDOWN)
        & (data["market_return_5d"] >= GOVERNANCE_MOMENTUM_REBOUND_RETURN)
    ).astype(int)
    future_paths = pd.concat([data["market_proxy_close"].shift(-offset) for offset in range(6)], axis=1)
    future_peak = future_paths.cummax(axis=1)
    data["future_market_max_drawdown_5d"] = ((future_peak - future_paths) / future_peak).max(axis=1)
    data["market_crash_label_5d"] = (data["future_market_max_drawdown_5d"] >= 0.05).astype(int)
    data["label_window_start"] = data["date"] + pd.offsets.BDay(1)
    data["label_window_end"] = data["date"] + pd.offsets.BDay(5)
    return data


def fit_serial_safety_model(daily: pd.DataFrame) -> dict:
    """Fit a small logistic safety model and freeze validation-only isotonic calibration."""
    data = daily.dropna(subset=[*SAFETY_FEATURES, "market_crash_label_5d"]).copy().sort_values("date")
    if len(data) < 80:
        raise ValueError("At least 80 daily safety rows are required")
    train_end = int(len(data) * GOVERNANCE_SAFETY_TRAIN_RATIO)
    validation_start = train_end + GOVERNANCE_TRAIN_PURGE_PERIODS
    validation_end = validation_start + int(len(data) * GOVERNANCE_SAFETY_VALIDATION_RATIO)
    test_start = validation_end + GOVERNANCE_TRAIN_EMBARGO_PERIODS
    train = data.iloc[:train_end].copy()
    validation = data.iloc[validation_start:validation_end].copy()
    test = data.iloc[test_start:].copy()
    if validation.empty or test.empty:
        raise ValueError("Safety train/validation/test split is empty after purge and embargo")
    mean = train[SAFETY_FEATURES].mean()
    std = train[SAFETY_FEATURES].std(ddof=0).replace(0.0, 1.0)
    x_train = ((train[SAFETY_FEATURES] - mean) / std).to_numpy(dtype=float)
    y_train = train["market_crash_label_5d"].to_numpy(dtype=float)
    costs = build_conditional_safety_cost_matrix(train)
    coefficients, intercept = _fit_weighted_logistic(x_train, y_train, costs)
    raw_validation = _sigmoid(((validation[SAFETY_FEATURES] - mean) / std).to_numpy(dtype=float) @ coefficients + intercept)
    calibration = fit_isotonic_calibration_table(raw_validation, validation["market_crash_label_5d"])
    calibrated_validation = np.interp(raw_validation, calibration["raw_probability"], calibration["calibrated_probability"])
    warning_threshold = select_cost_sensitive_threshold(
        validation["market_crash_label_5d"],
        calibrated_validation,
        costs,
    )
    raw_test = _sigmoid(((test[SAFETY_FEATURES] - mean) / std).to_numpy(dtype=float) @ coefficients + intercept)
    calibrated_test = np.interp(raw_test, calibration["raw_probability"], calibration["calibrated_probability"])
    evaluation = evaluate_safety_predictions(
        test["market_crash_label_5d"],
        calibrated_test,
        costs,
        split="frozen_test",
        threshold=warning_threshold,
    )
    evaluation["train_rows"] = len(train)
    evaluation["validation_rows"] = len(validation)
    evaluation["test_rows"] = len(test)
    evaluation["validation_positive_count"] = int(validation["market_crash_label_5d"].sum())
    evaluation["activation_gate_passed"] = bool(
        evaluation["validation_positive_count"] >= 5
        and evaluation["false_negative_count"] == 0
    )
    model = {
        "model_name": "calibrated_logistic_crash_probability",
        "registry_stage": "candidate",
        "feature_names": SAFETY_FEATURES,
        "preprocessing_mean": {key: float(value) for key, value in mean.items()},
        "preprocessing_std": {key: float(value) for key, value in std.items()},
        "coefficients": [float(value) for value in coefficients],
        "intercept": float(intercept),
        "cost_matrix": asdict(costs),
        "purge_periods": GOVERNANCE_TRAIN_PURGE_PERIODS,
        "embargo_periods": GOVERNANCE_TRAIN_EMBARGO_PERIODS,
        "calibration": "isotonic_validation_only",
        "warning_threshold": warning_threshold,
        "activation_policy": "candidate_only_until_shadow_and_manual_review",
        "activation_gate_passed": evaluation["activation_gate_passed"],
        "activation_block_reason": (
            ""
            if evaluation["activation_gate_passed"]
            else "insufficient_validation_crash_examples_or_frozen_test_false_negatives"
        ),
    }
    return {"model": model, "calibration": calibration, "evaluation": pd.DataFrame([evaluation]), "cost_matrix": costs}


def build_conditional_safety_cost_matrix(train: pd.DataFrame) -> SafetyCostMatrix:
    normal_vol = pd.to_numeric(train["market_volatility_20d"], errors="coerce").abs()
    normal_scale = float(normal_vol[normal_vol > 0].median()) if (normal_vol > 0).any() else 0.01
    crash_dd = pd.to_numeric(train.loc[train["market_crash_label_5d"] == 1, "future_market_max_drawdown_5d"], errors="coerce")
    crash_scale = float(crash_dd.median()) if crash_dd.notna().any() else 0.05
    ratio = min(max(crash_scale / max(normal_scale, 1e-6), 1.0), 25.0)
    return SafetyCostMatrix(false_positive_cost=1.0, false_negative_cost=ratio)


def select_cost_sensitive_threshold(outcomes, probabilities, costs: SafetyCostMatrix) -> float:
    candidates = sorted(set([0.01, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50, *np.asarray(probabilities, dtype=float).tolist()]))
    scored = []
    for threshold in candidates:
        result = evaluate_safety_predictions(outcomes, probabilities, costs, split="validation", threshold=threshold)
        scored.append((result["weighted_conditional_cost"], float(threshold)))
    return min(scored, key=lambda item: (item[0], item[1]))[1]


def evaluate_safety_predictions(outcomes, probabilities, costs: SafetyCostMatrix, *, split, threshold=0.20) -> dict:
    y = np.asarray(outcomes, dtype=float)
    p = np.asarray(probabilities, dtype=float)
    prediction = p >= float(threshold)
    false_positive = (prediction == 1) & (y == 0)
    false_negative = (prediction == 0) & (y == 1)
    weighted_cost = (
        false_positive.sum() * costs.false_positive_cost
        + false_negative.sum() * costs.false_negative_cost
    ) / max(len(y), 1)
    return {
        "split": split,
        "brier_score": float(np.mean(np.square(p - y))),
        "weighted_conditional_cost": float(weighted_cost),
        "false_positive_count": int(false_positive.sum()),
        "false_negative_count": int(false_negative.sum()),
        "positive_rate": float(y.mean()) if len(y) else 0.0,
        "warning_threshold": float(threshold),
    }


def build_bounded_bandit_actions() -> pd.DataFrame:
    baseline = BanditAction("baseline", GOVERNANCE_DEFAULT_TOP_N, 5, GOVERNANCE_DEFAULT_TURNOVER_BUDGET)
    actions = [
        baseline,
        BanditAction("top_n_defensive", 18, 5, GOVERNANCE_DEFAULT_TURNOVER_BUDGET),
        BanditAction("top_n_broad", 22, 5, GOVERNANCE_DEFAULT_TURNOVER_BUDGET),
        BanditAction("holding_longer", GOVERNANCE_DEFAULT_TOP_N, 6, GOVERNANCE_DEFAULT_TURNOVER_BUDGET),
        BanditAction("turnover_lower", GOVERNANCE_DEFAULT_TOP_N, 5, GOVERNANCE_DEFAULT_TURNOVER_BUDGET * 0.8),
        BanditAction("turnover_higher", GOVERNANCE_DEFAULT_TOP_N, 5, GOVERNANCE_DEFAULT_TURNOVER_BUDGET * 1.2),
    ]
    validate_bandit_actions(actions, baseline=baseline, bound_ratio=GOVERNANCE_BANDIT_ACTION_BOUND_RATIO)
    return pd.DataFrame([asdict(action) for action in actions]).assign(
        registry_stage="shadow_only",
        minimum_shadow_days=GOVERNANCE_BANDIT_SHADOW_DAYS,
    )


def build_initial_transition_protocol() -> dict:
    return {
        "mode": "sell_only_transition",
        "transition_days": GOVERNANCE_INITIAL_TRANSITION_DAYS,
        "allow_new_buys": False,
        "allow_safety_deleveraging": True,
        "allow_hard_qualification_exit": True,
        "reputation_updates_enabled": False,
        "completion_rule": "transition_days_elapsed_and_account_reconciliation_passed",
    }


def build_monitoring_rollback_policy() -> dict:
    return {
        "monitoring_frequency": "daily_after_close",
        "rollback_target": "rules_based_president",
        "automatic_rollback_conditions": {
            "account_reconciliation_error_abs_gt": 1e-8,
            "missing_price_position_count_gt": 0,
            "safety_proxy_lag_days_gt": 1,
            "unresolved_safety_exposure_gt": 0.05,
            "model_feature_schema_mismatch": True,
        },
        "manual_review_conditions": {
            "rolling_20d_drawdown_gt": 0.10,
            "safety_sell_flow_impact_estimate_gt": 0.02,
            "candidate_weight_saturation_ratio_gt": 0.20,
        },
        "bandit_activation": "shadow_only_until_252_days_and_phase_gate_pass",
    }


def build_local_model_registry(congress, training, actions) -> dict:
    entries = []
    for row in congress.itertuples(index=False):
        entries.append(
            {
                "model_name": row.model_name,
                "model_family": row.model_family,
                "institution": row.institution,
                "stage": row.registry_stage,
                "version": DECISION_COUNCIL_VERSION,
            }
        )
    entries.append(
        {
            "model_name": training["model"]["model_name"],
            "model_family": "safety_probability",
            "institution": "safety_council",
            "stage": "candidate",
            "version": DECISION_COUNCIL_VERSION,
            "manual_review_required": True,
        }
    )
    return {
        "registry_version": "local_json_registry_v1",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "allowed_stages": ["candidate", "validated", "shadow_only", "champion", "retired", "active_rule"],
        "entries": entries,
        "bandit_actions": actions.to_dict(orient="records"),
    }


def build_phase_gate_report(training, registry) -> pd.DataFrame:
    safety_eval = training["evaluation"].iloc[0]
    rows = [
        ("P0", "accounting_execution_correctness", "implemented", "last-known pricing, corporate-action fallback, double NAV"),
        ("P0.5", "daily_account_reconciliation", "implemented", "independent shares * mark_price + cash audit"),
        ("P1", "sticky_rules_baseline", "implemented", "weekly meeting, rank buffer, minimum hold, partial adjustment"),
        ("P1.5", "execution_impact_proxy", "implemented_exploratory", "daily square-root participation proxy; VWAP calibration pending"),
        ("P2", "model_congress_catalog", "implemented", f"registered_models={len(registry['entries'])}"),
        (
            "P3",
            "calibrated_safety_candidate",
            "validated_candidate" if bool(safety_eval["activation_gate_passed"]) else "candidate_blocked",
            f"frozen_test_brier={float(safety_eval['brier_score']):.6f}; "
            f"validation_positive_count={int(safety_eval['validation_positive_count'])}; "
            f"frozen_test_false_negatives={int(safety_eval['false_negative_count'])}",
        ),
        ("P4", "shadow_reputation_admission", "implemented_gate", "252 shadow days and OOS admission required"),
        ("P5", "bounded_contextual_bandit", "shadow_only", "finite one-dimension actions within +/-20%"),
        ("P6", "monitoring_and_rollback", "implemented", "daily rollback contract targets rules_based_president"),
        ("P7", "registry_lineage_reproducibility", "implemented_exploratory", "local registry and manifest; formal review still required"),
    ]
    return pd.DataFrame(rows, columns=["phase", "gate", "status", "detail"])


def build_industrial_manifest(feature_path, saved, training) -> dict:
    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "decision_council_version": DECISION_COUNCIL_VERSION,
        "execution_mode": "serial_low_memory",
        "feature_input": file_fingerprint(feature_path),
        "code_fingerprints": {
            path: code_file_fingerprint(path)
            for path in [
                "config.py",
                "functions/decision_council/industrial_pipeline.py",
                "functions/decision_council/advanced_policies.py",
                "functions/decision_council/policy.py",
                "functions/decision_council/runner.py",
            ]
        },
        "artifacts": {name: file_fingerprint(path) for name, path in saved.items()},
        "feature_selection_log": {"safety_model": SAFETY_FEATURES},
        "feature_preprocessing_params": {
            "safety_model_mean": training["model"]["preprocessing_mean"],
            "safety_model_std": training["model"]["preprocessing_std"],
        },
        "threshold_migration_log": [
            {
                "status": "temporary_frozen_exploratory",
                "entry_rank_limit": 20,
                "hold_rank_limit": GOVERNANCE_HOLD_RANK_LIMIT,
                "note": "Replace with endogenous no-trade region after VWAP impact calibration.",
            }
        ],
        "formal_activation_blocked": True,
        "formal_activation_block_reason": "PIT external timestamps, VWAP impact calibration, shadow admission, and independent review remain required.",
    }


def build_research_reference_catalog() -> pd.DataFrame:
    rows = [
        ("paper", "Dynamic Trading with Predictable Returns and Transaction Costs", "https://www.nber.org/papers/w15205", "No-trade region and cost-aware portfolio adjustment"),
        ("paper", "Machine Learning in Asset Pricing", "https://www.nber.org/papers/w25398", "OOF evaluation and high-dimensional alpha modeling"),
        ("paper", "Momentum Crashes", "https://www.nber.org/papers/w20439", "Momentum rebound regime control"),
        ("paper", "The Probability of Backtest Overfitting", "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253", "Backtest overfitting and CSCV/PBO"),
        ("official_docs", "Probability calibration", "https://scikit-learn.org/stable/modules/calibration.html", "Validation-only probability calibration"),
        ("official_docs", "TimeSeriesSplit", "https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html", "Time-ordered model validation"),
        ("official_docs", "MLflow Model Registry", "https://mlflow.org/docs/latest/ml/model-registry/", "Candidate, shadow, champion, retired lifecycle"),
        ("governance", "SR 11-7 Model Risk Management", "https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm", "Validation independence, governance, monitoring"),
        ("course", "Stanford CS229 Machine Learning", "https://cs229.stanford.edu/", "Supervised learning and regularization foundations"),
        ("course", "CFA Trade Strategy and Execution", "https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/trade-strategy-execution", "Execution benchmarking and implementation shortfall"),
    ]
    return pd.DataFrame(rows, columns=["source_type", "title", "url", "applied_to"])


def _stream_market_proxy_close(feature_path, *, columns, batch_size):
    import pyarrow.parquet as pq

    close_col = "close_nominal" if "close_nominal" in columns else "close"
    rows = []
    parquet = pq.ParquetFile(feature_path)
    for batch in parquet.iter_batches(batch_size=int(batch_size), columns=["date", "symbol", close_col]):
        part = batch.to_pandas()
        part["date"] = pd.to_datetime(part["date"], errors="coerce")
        part[close_col] = pd.to_numeric(part[close_col], errors="coerce")
        proxy = part[part["symbol"].astype(str) == "sh510300"][["date", close_col]].copy()
        if not proxy.empty:
            rows.append(proxy.rename(columns={close_col: "market_proxy_close"}))
    if not rows:
        raise ValueError("Safety proxy sh510300 is required for industrial safety training")
    return pd.concat(rows, ignore_index=True).dropna().drop_duplicates("date", keep="last")


def _fit_weighted_logistic(x, y, costs: SafetyCostMatrix):
    coefficients = np.zeros(x.shape[1], dtype=float)
    intercept = 0.0
    weights = np.where(y >= 0.5, costs.false_negative_cost, costs.false_positive_cost)
    for _ in range(int(GOVERNANCE_SAFETY_MAX_ITERATIONS)):
        probability = _sigmoid(x @ coefficients + intercept)
        error = (probability - y) * weights
        gradient = x.T @ error / len(x) + GOVERNANCE_SAFETY_L2 * coefficients
        intercept_gradient = float(error.mean())
        coefficients -= GOVERNANCE_SAFETY_LEARNING_RATE * gradient
        intercept -= GOVERNANCE_SAFETY_LEARNING_RATE * intercept_gradient
    return coefficients, intercept


def _sigmoid(values):
    clipped = np.clip(np.asarray(values, dtype=float), -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _write_csv(frame, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _write_json(payload, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path
