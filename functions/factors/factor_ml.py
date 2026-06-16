# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
from pandas.tseries.offsets import BDay

from functions.labels import default_label_specs
from functions.progress import progress_iter, progress_step

try:
    import xgboost as xgb
except ImportError:
    xgb = None

try:
    import lightgbm as lgb
except ImportError:
    lgb = None

USE_EXTERNAL_TREE_MODELS = False

DEFAULT_TARGET_COL = "_ml_target"
DEFAULT_LOOKBACK_DAYS = 500
DEFAULT_LABEL_HORIZON = 5
DEFAULT_FEATURE_SUFFIX_PRIORITY = (
    "_neutralized",
    "_z",
    "_robust",
    "_winsor",
)
BASE_ML_FEATURE_COLUMNS = (
    "ret_1",
    "ret_5",
    "ret_10",
    "ret_20",
    "ret_60",
    "close_to_ma20",
    "close_to_ma60",
    "volatility_10",
    "volatility_20",
    "volatility_60",
    "amplitude",
    "intraday_ret",
    "upper_shadow",
    "lower_shadow",
    "body_ratio",
    "amount_ratio_20",
    "score_mom_lowvol",
)

MODEL_CONFIGS = {
    "elasticnet": {
        "min_train_rows": 240,
        "max_features": 16,
        "alpha": 0.05,
    },
    "xgboost": {
        "min_train_rows": 240,
        "max_features": 20,
        "alpha": 0.08,
    },
    "lightgbm": {
        "min_train_rows": 240,
        "max_features": 20,
        "alpha": 0.08,
    },
}


def runtime_model_name(model_type: str) -> str:
    if model_type == "elasticnet":
        return "elasticnet_linear_shrinkage"
    if model_type == "xgboost":
        return "xgboost_regressor" if USE_EXTERNAL_TREE_MODELS and xgb is not None else "linear_shrinkage_xgb_proxy"
    if model_type == "lightgbm":
        return "lightgbm_regressor" if USE_EXTERNAL_TREE_MODELS and lgb is not None else "linear_shrinkage_lgb_proxy"
    raise ValueError("model_type must be 'elasticnet', 'xgboost', or 'lightgbm'")


def list_ml_baseline_models():
    return tuple(MODEL_CONFIGS.keys())


def build_ml_baseline_contract():
    rows = []
    for model_name, config in MODEL_CONFIGS.items():
        rows.append(
            {
                "model_name": model_name,
                "min_train_rows": config["min_train_rows"],
                "max_features": config["max_features"],
                "alpha": config["alpha"],
                "default_target_col": DEFAULT_TARGET_COL,
                "default_label_horizon": DEFAULT_LABEL_HORIZON,
            }
        )
    return pd.DataFrame(rows)


def compute_factor(
    df_factors,
    target_col=None,
    model_type="elasticnet",
    rebalance_dates=None,
    lookback_days=DEFAULT_LOOKBACK_DAYS,
):
    """Generate out-of-sample ML scores on rebalance dates only."""
    if model_type not in MODEL_CONFIGS:
        raise ValueError("model_type must be 'elasticnet', 'xgboost', or 'lightgbm'")

    data = _prepare_ml_frame(df_factors=df_factors, target_col=target_col)
    config = MODEL_CONFIGS[model_type]
    rebalance_index = _normalize_rebalance_dates(data=data, rebalance_dates=rebalance_dates)
    rows = []
    diagnostics = []

    progress_step(f"ML factor {model_type}: rebalance dates={len(rebalance_index)}")
    for rebalance_date in progress_iter(
        rebalance_index,
        desc=f"ml {model_type}",
        total=len(rebalance_index),
    ):
        train_start = rebalance_date - pd.Timedelta(days=lookback_days)
        label_safe_cutoff = rebalance_date - BDay(DEFAULT_LABEL_HORIZON)
        train_mask = (data["date"] < label_safe_cutoff) & (data["date"] >= train_start)
        predict_mask = data["date"] == rebalance_date

        train_data = data.loc[train_mask].copy()
        predict_data = data.loc[predict_mask].copy()
        if train_data.empty or predict_data.empty:
            diagnostics.append(
                _diagnostic_row(
                    model_family="ml_baseline",
                    strategy_id=model_type,
                    rebalance_date=rebalance_date,
                    lookback_days=lookback_days,
                    required_min_train_rows=config["min_train_rows"],
                    actual_train_rows=len(train_data),
                    predict_rows=len(predict_data),
                    status="skipped",
                    skip_reason="empty_train_or_predict",
                )
            )
            continue

        train_data[DEFAULT_TARGET_COL] = train_data[DEFAULT_TARGET_COL].replace(
            [np.inf, -np.inf],
            np.nan,
        )
        train_data = train_data.dropna(subset=[DEFAULT_TARGET_COL, "symbol"])
        if len(train_data) < config["min_train_rows"]:
            diagnostics.append(
                _diagnostic_row(
                    model_family="ml_baseline",
                    strategy_id=model_type,
                    rebalance_date=rebalance_date,
                    lookback_days=lookback_days,
                    required_min_train_rows=config["min_train_rows"],
                    actual_train_rows=len(train_data),
                    predict_rows=len(predict_data),
                    status="skipped",
                    skip_reason="insufficient_train_rows",
                )
            )
            continue

        feature_cols = _select_feature_columns(
            train_data=train_data,
            max_features=config["max_features"],
        )
        if not feature_cols:
            diagnostics.append(
                _diagnostic_row(
                    model_family="ml_baseline",
                    strategy_id=model_type,
                    rebalance_date=rebalance_date,
                    lookback_days=lookback_days,
                    required_min_train_rows=config["min_train_rows"],
                    actual_train_rows=len(train_data),
                    predict_rows=len(predict_data),
                    status="skipped",
                    skip_reason="no_feature_columns",
                )
            )
            continue

        scores = _fit_predict_model(
            train_frame=train_data,
            predict_frame=predict_data,
            feature_cols=feature_cols,
            target_col=DEFAULT_TARGET_COL,
            model_type=model_type,
            alpha=config["alpha"],
        )

        scored = predict_data[["date", "symbol"]].copy()
        scored["score_ml"] = scores
        scored["ml_model"] = model_type
        scored["requested_model"] = model_type
        scored["runtime_model"] = runtime_model_name(model_type)
        scored["ml_runtime_mode"] = "tree_model" if scored["runtime_model"].iloc[0].endswith("_regressor") else "proxy_model"
        scored["ml_degradation_flag"] = (
            "ml_tree_model_proxy_used"
            if scored["ml_runtime_mode"].iloc[0] == "proxy_model" and model_type in {"xgboost", "lightgbm"}
            else ""
        )
        scored["training_window_days"] = lookback_days
        scored["label_purge_periods"] = DEFAULT_LABEL_HORIZON
        scored["fitted_feature_count"] = len(feature_cols)
        scored["feature_list"] = ",".join(feature_cols)
        scored["training_sample_count"] = len(train_data)
        rows.append(scored)
        diagnostics.append(
            _diagnostic_row(
                model_family="ml_baseline",
                strategy_id=model_type,
                rebalance_date=rebalance_date,
                lookback_days=lookback_days,
                required_min_train_rows=config["min_train_rows"],
                actual_train_rows=len(train_data),
                predict_rows=len(predict_data),
                status="scored",
                skip_reason="",
                runtime_model=scored["runtime_model"].iloc[0],
                requested_model=model_type,
                fitted_feature_count=len(feature_cols),
            )
        )

    if not rows:
        empty = pd.DataFrame(
            columns=[
                "date",
                "symbol",
                "score_ml",
                "ml_model",
                "requested_model",
                "runtime_model",
                "ml_runtime_mode",
                "ml_degradation_flag",
                "training_window_days",
                "label_purge_periods",
                "fitted_feature_count",
                "feature_list",
                "training_sample_count",
            ]
        )
        empty.attrs["training_diagnostics"] = pd.DataFrame(diagnostics)
        return empty

    result = pd.concat(rows, ignore_index=True)
    result.attrs["training_diagnostics"] = pd.DataFrame(diagnostics)
    return result


def _diagnostic_row(
    *,
    model_family,
    strategy_id,
    rebalance_date,
    lookback_days,
    required_min_train_rows,
    actual_train_rows,
    predict_rows,
    status,
    skip_reason,
    runtime_model="",
    requested_model="",
    fitted_feature_count=0,
):
    return {
        "model_family": model_family,
        "strategy_id": str(strategy_id),
        "rebalance_date": pd.Timestamp(rebalance_date),
        "lookback_days": int(lookback_days),
        "required_min_train_rows": int(required_min_train_rows),
        "actual_train_rows": int(actual_train_rows),
        "predict_rows": int(predict_rows),
        "status": str(status),
        "skip_reason": str(skip_reason),
        "requested_model": str(requested_model or strategy_id),
        "runtime_model": str(runtime_model),
        "fitted_feature_count": int(fitted_feature_count),
    }


def _prepare_ml_frame(df_factors, target_col):
    label_name = f"future_ret_{DEFAULT_LABEL_HORIZON}"
    keep_cols = ["date", "symbol"]
    if target_col is not None:
        keep_cols.append(target_col)
    elif label_name in df_factors.columns:
        keep_cols.append(label_name)
    else:
        keep_cols.append("close")

    for base_col in BASE_ML_FEATURE_COLUMNS:
        for suffix in ("", *DEFAULT_FEATURE_SUFFIX_PRIORITY):
            col = f"{base_col}{suffix}"
            if col in df_factors.columns:
                keep_cols.append(col)

    keep_cols = list(dict.fromkeys(col for col in keep_cols if col in df_factors.columns))
    data = df_factors.loc[:, keep_cols].copy()
    data["date"] = pd.to_datetime(data["date"])
    data = data.sort_values(["symbol", "date"])

    if target_col is None:
        if label_name in data.columns:
            data[DEFAULT_TARGET_COL] = pd.to_numeric(data[label_name], errors="coerce")
        else:
            future_close = data.groupby("symbol")["close"].shift(-DEFAULT_LABEL_HORIZON)
            data[DEFAULT_TARGET_COL] = future_close / data["close"] - 1
    else:
        data[DEFAULT_TARGET_COL] = pd.to_numeric(data[target_col], errors="coerce")

    return data


def _normalize_rebalance_dates(data, rebalance_dates):
    if rebalance_dates is None:
        rebalance_dates = data["date"].drop_duplicates().sort_values()
    return pd.to_datetime(pd.Series(rebalance_dates)).dropna().drop_duplicates().sort_values()


def _select_feature_columns(train_data, max_features):
    candidate_cols = []
    preferred_aliases = _build_preferred_feature_aliases(train_data.columns)
    for col in train_data.columns:
        if col in {"date", "symbol", DEFAULT_TARGET_COL}:
            continue
        if col.startswith("future_ret_") or col.startswith("reward_") or col.startswith("score_"):
            continue
        if col in preferred_aliases and preferred_aliases[col] != col:
            continue
        if not pd.api.types.is_numeric_dtype(train_data[col]):
            continue
        if train_data[col].notna().sum() < 60:
            continue
        candidate_cols.append(col)

    if not candidate_cols:
        return []

    scored_candidates = []
    for col in candidate_cols:
        pair = train_data[[col, DEFAULT_TARGET_COL]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(pair) < 60:
            score = 0.0
        else:
            corr = pair[col].corr(pair[DEFAULT_TARGET_COL])
            score = abs(corr) if pd.notna(corr) else 0.0
        scored_candidates.append((col, score))

    scored_candidates.sort(key=lambda item: (-item[1], item[0]))
    return [col for col, _ in scored_candidates[:max_features]]


def _build_preferred_feature_aliases(columns):
    columns = list(columns)
    alias_map = {}
    normalized_candidates = {}
    for col in columns:
        for suffix in DEFAULT_FEATURE_SUFFIX_PRIORITY:
            if col.endswith(suffix):
                base = col[: -len(suffix)]
                normalized_candidates.setdefault(base, col)
                break
        else:
            normalized_candidates.setdefault(col, col)

    for col in columns:
        alias_map[col] = normalized_candidates.get(col, col)
    return alias_map


def _fit_predict_model(train_frame, predict_frame, feature_cols, target_col, model_type, alpha):
    x_train, x_predict = _prepare_model_matrices(
        train_frame=train_frame,
        predict_frame=predict_frame,
        feature_cols=feature_cols,
    )
    y_train = train_frame[target_col].fillna(0.0).to_numpy(dtype=float)

    if model_type == "elasticnet":
        return _linear_shrinkage_predict(x_train, y_train, x_predict, alpha=alpha)

    if model_type == "xgboost":
        if USE_EXTERNAL_TREE_MODELS and xgb is not None:
            model = xgb.XGBRegressor(
                objective="reg:squarederror",
                n_estimators=120,
                max_depth=3,
                learning_rate=0.05,
                min_child_weight=20,
                subsample=0.8,
                colsample_bytree=0.8,
                reg_alpha=0.2,
                reg_lambda=1.0,
                random_state=42,
            )
            model.fit(x_train, y_train)
            return model.predict(x_predict)

        transformed_train = np.concatenate([x_train, np.tanh(x_train), x_train ** 2], axis=1)
        transformed_predict = np.concatenate([x_predict, np.tanh(x_predict), x_predict ** 2], axis=1)
        return _linear_shrinkage_predict(transformed_train, y_train, transformed_predict, alpha=alpha)

    if model_type == "lightgbm":
        if USE_EXTERNAL_TREE_MODELS and lgb is not None:
            model = lgb.LGBMRegressor(
                n_estimators=160,
                learning_rate=0.05,
                num_leaves=15,
                min_child_samples=60,
                subsample=0.8,
                colsample_bytree=0.8,
                reg_alpha=0.2,
                reg_lambda=1.0,
                random_state=42,
                verbose=-1,
            )
            model.fit(x_train, y_train)
            return model.predict(x_predict)

        transformed_train = np.concatenate([x_train, np.sign(x_train), np.abs(x_train)], axis=1)
        transformed_predict = np.concatenate(
            [x_predict, np.sign(x_predict), np.abs(x_predict)],
            axis=1,
        )
        return _linear_shrinkage_predict(transformed_train, y_train, transformed_predict, alpha=alpha)

    raise ValueError("model_type must be 'elasticnet', 'xgboost', or 'lightgbm'")


def _prepare_model_matrices(train_frame, predict_frame, feature_cols):
    x_train = train_frame[feature_cols].replace([np.inf, -np.inf], np.nan)
    x_predict = predict_frame[feature_cols].replace([np.inf, -np.inf], np.nan)

    fill_values = x_train.median(numeric_only=True).fillna(0.0)
    x_train = x_train.fillna(fill_values)
    x_predict = x_predict.fillna(fill_values)

    mean = x_train.mean()
    std = x_train.std(ddof=0).replace(0, 1.0).fillna(1.0)

    x_train = ((x_train - mean) / std).to_numpy(dtype=float)
    x_predict = ((x_predict - mean) / std).to_numpy(dtype=float)
    return x_train, x_predict


def _linear_shrinkage_predict(x_train, y_train, x_predict, alpha):
    if x_train.ndim != 2 or x_train.shape[1] == 0:
        return np.zeros(len(x_predict), dtype=float)

    xtx = x_train.T @ x_train
    penalty = np.eye(x_train.shape[1], dtype=float) * alpha
    xty = x_train.T @ y_train
    coef = np.linalg.solve(xtx + penalty, xty)
    return x_predict @ coef
