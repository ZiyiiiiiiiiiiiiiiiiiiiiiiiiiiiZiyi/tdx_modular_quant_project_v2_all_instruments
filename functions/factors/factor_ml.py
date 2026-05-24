# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd

try:
    import xgboost as xgb
except ImportError:
    xgb = None

try:
    import lightgbm as lgb
except ImportError:
    lgb = None


DEFAULT_TARGET_COL = "_ml_target"
DEFAULT_LOOKBACK_DAYS = 500
DEFAULT_LABEL_HORIZON = 5

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

    for rebalance_date in rebalance_index:
        train_start = rebalance_date - pd.Timedelta(days=lookback_days)
        train_mask = (data["date"] < rebalance_date) & (data["date"] >= train_start)
        predict_mask = data["date"] == rebalance_date

        train_data = data.loc[train_mask].copy()
        predict_data = data.loc[predict_mask].copy()
        if train_data.empty or predict_data.empty:
            continue

        train_data[DEFAULT_TARGET_COL] = train_data[DEFAULT_TARGET_COL].replace(
            [np.inf, -np.inf],
            np.nan,
        )
        train_data = train_data.dropna(subset=[DEFAULT_TARGET_COL, "symbol"])
        if len(train_data) < config["min_train_rows"]:
            continue

        feature_cols = _select_feature_columns(
            train_data=train_data,
            max_features=config["max_features"],
        )
        if not feature_cols:
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
        scored["training_window_days"] = lookback_days
        scored["fitted_feature_count"] = len(feature_cols)
        scored["feature_list"] = ",".join(feature_cols)
        rows.append(scored)

    if not rows:
        return pd.DataFrame(
            columns=[
                "date",
                "symbol",
                "score_ml",
                "ml_model",
                "training_window_days",
                "fitted_feature_count",
                "feature_list",
            ]
        )

    return pd.concat(rows, ignore_index=True)


def _prepare_ml_frame(df_factors, target_col):
    data = df_factors.copy()
    data["date"] = pd.to_datetime(data["date"])
    data = data.sort_values(["symbol", "date"]).copy()

    if target_col is None:
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
    for col in train_data.columns:
        if col in {"date", "symbol", DEFAULT_TARGET_COL}:
            continue
        if col.startswith("future_ret_") or col.startswith("reward_") or col.startswith("score_"):
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
        if xgb is not None:
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
        if lgb is not None:
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
