# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
from pandas.tseries.offsets import BDay

from functions.labels import LABEL_DEFAULT_HORIZONS


GROUP_COL = "symbol"
EPSILON = 1e-9

LEARNING_PROFILES = {
    "short": {
        "lookback_days": 120,
        "max_features": 8,
        "qubit_count": 4,
        "ridge_alpha": 1.0,
        "min_train_rows": 120,
    },
    "medium": {
        "lookback_days": 250,
        "max_features": 16,
        "qubit_count": 8,
        "ridge_alpha": 0.7,
        "min_train_rows": 250,
    },
    "long": {
        "lookback_days": 500,
        "max_features": 24,
        "qubit_count": 12,
        "ridge_alpha": 0.5,
        "min_train_rows": 400,
    },
}

CLASSIC_REWARD_METHODS = {
    "forward_return": "未来5日收益",
    "risk_adjusted": "未来10日风险调整收益",
}

QUBIT_REWARD_METHODS = {
    "phase_alignment": "未来10日相位收益",
    "stability_tunneling": "未来20日稳定穿透收益",
}

BASE_FEATURE_PRIORITY = [
    "ret_1",
    "ret_5",
    "ret_10",
    "ret_20",
    "ret_60",
    "ma_5",
    "ma_10",
    "ma_20",
    "ma_60",
    "ma_120",
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
    "amount_ma20",
    "amount_ratio_20",
    "volume_ma_5",
    "volume_ma_10",
    "volume_ma_20",
    "volume_ma_60",
    "volume_ma_120",
    "score_mom_lowvol",
]


def get_learning_strategy_configs():
    configs = {}

    for profile_name, profile in LEARNING_PROFILES.items():
        lookback_days = profile["lookback_days"]
        max_features = profile["max_features"]
        qubit_count = profile["qubit_count"]

        for reward_method, reward_label in CLASSIC_REWARD_METHODS.items():
            strategy_name = f"classic_ml_{reward_method}_{profile_name}"
            configs[strategy_name] = {
                "module": "classic_ml",
                "reward_method": reward_method,
                "reward_label": reward_label,
                "profile_name": profile_name,
                "description": (
                    f"经典机器学习 / 奖励={reward_label} / 档位={profile_name} "
                    f"(训练窗口{lookback_days}天, 特征预算{max_features})"
                ),
            }

        for reward_method, reward_label in QUBIT_REWARD_METHODS.items():
            strategy_name = f"quantum_inspired_{reward_method}_{profile_name}"
            configs[strategy_name] = {
                "module": "quantum_inspired",
                "reward_method": reward_method,
                "reward_label": reward_label,
                "profile_name": profile_name,
                "description": (
                    f"量子比特学习(量子启发式) / 奖励={reward_label} / 档位={profile_name} "
                    f"(训练窗口{lookback_days}天, 特征预算{max_features}, qubit={qubit_count})"
                ),
            }

    return configs


LEARNING_STRATEGY_CONFIGS = get_learning_strategy_configs()
LEARNING_STRATEGY_DESCRIPTIONS = {
    strategy_name: config["description"]
    for strategy_name, config in LEARNING_STRATEGY_CONFIGS.items()
}


def build_learning_baseline_contract():
    rows = []
    for strategy_name, config in LEARNING_STRATEGY_CONFIGS.items():
        profile = LEARNING_PROFILES[config["profile_name"]]
        rows.append(
            {
                "strategy_name": strategy_name,
                "module": config["module"],
                "reward_method": config["reward_method"],
                "profile_name": config["profile_name"],
                "lookback_days": profile["lookback_days"],
                "max_features": profile["max_features"],
                "qubit_count": profile["qubit_count"],
                "ridge_alpha": profile["ridge_alpha"],
                "min_train_rows": profile["min_train_rows"],
            }
        )
    return pd.DataFrame(rows)


def generate_learning_module_scores(df, rebalance_dates):
    data = _prepare_learning_frame(df)
    score_tables = {}

    for strategy_name, config in LEARNING_STRATEGY_CONFIGS.items():
        score_tables[strategy_name] = _score_one_strategy(
            data=data,
            rebalance_dates=rebalance_dates,
            module_name=config["module"],
            reward_method=config["reward_method"],
            profile_name=config["profile_name"],
        )

    return score_tables


def _prepare_learning_frame(df):
    data = df.copy()
    data["date"] = pd.to_datetime(data["date"])
    data = data.sort_values([GROUP_COL, "date"]).copy()
    grouped = data.groupby(GROUP_COL, group_keys=False)

    for horizon in LABEL_DEFAULT_HORIZONS:
        label_name = f"future_ret_{horizon}"
        if label_name not in data.columns:
            future_close = grouped["close"].shift(-horizon)
            data[label_name] = future_close / data["close"] - 1

    data["reward_classic_forward_return"] = data["future_ret_5"]
    data["reward_classic_risk_adjusted"] = data["future_ret_10"] / (
        data["volatility_20"].abs() + 0.02
    )
    data["reward_qubit_phase_alignment"] = np.tanh(
        data["future_ret_10"].fillna(0) * 12
    ) * (1 - data["body_ratio"].fillna(0).clip(0, 1))
    data["reward_qubit_stability_tunneling"] = np.tanh(
        (
            data["future_ret_20"].fillna(0)
            / (data["volatility_20"].abs() + 0.03)
            + data["close_to_ma20"].fillna(0)
        ) * 4
    )
    return data


def _score_one_strategy(data, rebalance_dates, module_name, reward_method, profile_name):
    profile = LEARNING_PROFILES[profile_name]
    target_col = _target_column(module_name, reward_method)
    target_horizon = _target_horizon(module_name, reward_method)
    rows = []

    for rebalance_date in pd.to_datetime(pd.Series(rebalance_dates)).sort_values():
        train_start = rebalance_date - pd.Timedelta(days=profile["lookback_days"])
        label_safe_cutoff = rebalance_date - BDay(target_horizon)
        train_mask = (data["date"] < label_safe_cutoff) & (data["date"] >= train_start)
        predict_mask = data["date"] == rebalance_date

        train_data = data.loc[train_mask].copy()
        predict_data = data.loc[predict_mask].copy()
        if train_data.empty or predict_data.empty:
            continue

        train_data[target_col] = train_data[target_col].replace([np.inf, -np.inf], np.nan)
        train_data = train_data.dropna(subset=[target_col, "symbol"])
        if len(train_data) < profile["min_train_rows"]:
            continue

        feature_cols = _select_feature_columns(
            train_data=train_data,
            target_col=target_col,
            max_features=profile["max_features"],
        )
        if not feature_cols:
            continue

        if module_name == "classic_ml":
            scores = _fit_classic_model(
                train_frame=train_data,
                predict_frame=predict_data,
                feature_cols=feature_cols,
                target_col=target_col,
                alpha=profile["ridge_alpha"],
            )
        elif module_name == "quantum_inspired":
            scores = _fit_qubit_model(
                train_frame=train_data,
                predict_frame=predict_data,
                feature_cols=feature_cols,
                target_col=target_col,
                alpha=profile["ridge_alpha"],
                qubit_count=profile["qubit_count"],
            )
        else:
            raise ValueError(f"Unsupported module_name: {module_name}")

        scored = predict_data[["date", "symbol"]].copy()
        scored["score_learning"] = scores
        scored["learning_module"] = module_name
        scored["reward_method"] = reward_method
        scored["profile_tier"] = profile_name
        scored["training_window_days"] = profile["lookback_days"]
        scored["label_purge_periods"] = target_horizon
        scored["feature_budget"] = profile["max_features"]
        scored["qubit_count"] = profile["qubit_count"] if module_name == "quantum_inspired" else 0
        scored["fitted_feature_count"] = len(feature_cols)
        scored["feature_list"] = ",".join(feature_cols)
        rows.append(scored)

    if not rows:
        return pd.DataFrame(
            columns=[
                "date",
                "symbol",
                "score_learning",
                "learning_module",
                "reward_method",
                "profile_tier",
                "training_window_days",
                "label_purge_periods",
                "feature_budget",
                "qubit_count",
                "fitted_feature_count",
                "feature_list",
            ]
        )

    return pd.concat(rows, ignore_index=True)


def _select_feature_columns(train_data, target_col, max_features):
    candidates = []
    for col in BASE_FEATURE_PRIORITY:
        preferred_col = _preferred_feature_column(train_data.columns, col)
        if preferred_col not in train_data.columns:
            continue
        if not pd.api.types.is_numeric_dtype(train_data[preferred_col]):
            continue
        if train_data[preferred_col].notna().sum() < 30:
            continue
        candidates.append(preferred_col)

    if not candidates:
        return []

    correlations = []
    target = train_data[target_col]
    for col in candidates:
        pair = train_data[[col, target_col]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(pair) < 30:
            score = 0.0
        else:
            corr = pair[col].corr(pair[target_col])
            score = abs(corr) if pd.notna(corr) else 0.0
        correlations.append((col, score))

    correlations.sort(
        key=lambda item: (
            -item[1],
            BASE_FEATURE_PRIORITY.index(_base_feature_name(item[0])),
        )
    )
    selected = [col for col, _ in correlations[:max_features]]
    return selected


def _preferred_feature_column(columns, base_name):
    columns = set(columns)
    for suffix in ("_neutralized", "_z", "_robust", "_winsor"):
        candidate = f"{base_name}{suffix}"
        if candidate in columns:
            return candidate
    return base_name


def _base_feature_name(column_name):
    for suffix in ("_neutralized", "_z", "_robust", "_winsor"):
        if column_name.endswith(suffix):
            return column_name[: -len(suffix)]
    return column_name


def _fit_classic_model(train_frame, predict_frame, feature_cols, target_col, alpha):
    x_train, x_predict = _prepare_model_matrices(train_frame, predict_frame, feature_cols)
    y_train = train_frame[target_col].fillna(0).to_numpy(dtype=float)
    return _ridge_predict(x_train, y_train, x_predict, alpha)


def _fit_qubit_model(train_frame, predict_frame, feature_cols, target_col, alpha, qubit_count):
    x_train, x_predict = _prepare_model_matrices(train_frame, predict_frame, feature_cols)
    y_train = train_frame[target_col].fillna(0).to_numpy(dtype=float)

    projected_train, projected_predict = _qubit_projection(
        x_train=x_train,
        x_predict=x_predict,
        qubit_count=qubit_count,
        feature_count=len(feature_cols),
    )

    raw_score = _ridge_predict(projected_train, y_train, projected_predict, alpha)
    return np.tanh(raw_score * 3)


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


def _qubit_projection(x_train, x_predict, qubit_count, feature_count):
    rng = np.random.default_rng(20260524 + qubit_count + feature_count)
    projection = rng.normal(0, 1, size=(feature_count, qubit_count))
    projection /= np.linalg.norm(projection, axis=0, keepdims=True) + EPSILON

    train_phase = x_train @ projection
    predict_phase = x_predict @ projection

    train_state = np.concatenate(
        [np.sin(train_phase), np.cos(train_phase), np.tanh(train_phase)],
        axis=1,
    )
    predict_state = np.concatenate(
        [np.sin(predict_phase), np.cos(predict_phase), np.tanh(predict_phase)],
        axis=1,
    )
    return train_state, predict_state


def _target_column(module_name, reward_method):
    mapping = {
        ("classic_ml", "forward_return"): "reward_classic_forward_return",
        ("classic_ml", "risk_adjusted"): "reward_classic_risk_adjusted",
        ("quantum_inspired", "phase_alignment"): "reward_qubit_phase_alignment",
        ("quantum_inspired", "stability_tunneling"): "reward_qubit_stability_tunneling",
    }
    key = (module_name, reward_method)
    if key not in mapping:
        raise ValueError(f"Unsupported reward method: {key}")
    return mapping[key]


def _target_horizon(module_name, reward_method):
    mapping = {
        ("classic_ml", "forward_return"): 5,
        ("classic_ml", "risk_adjusted"): 10,
        ("quantum_inspired", "phase_alignment"): 10,
        ("quantum_inspired", "stability_tunneling"): 20,
    }
    return mapping[(module_name, reward_method)]


def _ridge_predict(x_train, y_train, x_predict, alpha):
    if x_train.ndim != 2 or x_train.shape[1] == 0:
        return np.zeros(len(x_predict), dtype=float)

    xtx = x_train.T @ x_train
    penalty = np.eye(x_train.shape[1], dtype=float) * alpha
    xty = x_train.T @ y_train
    coef = np.linalg.solve(xtx + penalty, xty)
    return x_predict @ coef
