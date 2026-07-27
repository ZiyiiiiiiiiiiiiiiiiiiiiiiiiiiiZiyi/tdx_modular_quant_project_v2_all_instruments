"""Adversarial train-versus-test drift diagnostics."""
from __future__ import annotations

import hashlib
from collections.abc import Iterable

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp


DRIFT_AUDIT_VERSION = "adversarial_drift_v1"


def build_adversarial_drift_reports(
    train_frame: pd.DataFrame,
    test_frame: pd.DataFrame,
    *,
    feature_columns: Iterable[str],
    group_column: str = "symbol",
    validation_fraction: float = 0.30,
    permutation_samples: int = 500,
    material_auc: float = 0.65,
    minimum_domain_rows: int = 100,
) -> dict[str, pd.DataFrame]:
    """Fit a held-out domain classifier and audit marginal feature shifts.

    A high held-out AUC means the feature vector itself reveals whether an
    observation came from the training or test period.  It is evidence of
    covariate drift, not by itself evidence that expected returns changed.
    """
    features = tuple(dict.fromkeys(str(column) for column in feature_columns))
    if not features:
        raise ValueError("at least one drift feature is required")
    required = {group_column, *features}
    missing_train = sorted(required - set(train_frame.columns))
    missing_test = sorted(required - set(test_frame.columns))
    if missing_train or missing_test:
        raise ValueError(f"drift audit missing columns: train={missing_train}, test={missing_test}")
    if not 0.05 <= float(validation_fraction) <= 0.50:
        raise ValueError("validation_fraction must be between 0.05 and 0.50")
    if int(permutation_samples) <= 0 or int(minimum_domain_rows) < 20:
        raise ValueError("permutation_samples and minimum_domain_rows are invalid")

    train = _prepare_domain(train_frame, features, group_column, 0)
    test = _prepare_domain(test_frame, features, group_column, 1)
    marginal = _marginal_drift(train, test, features)
    counts = {"train": len(train), "test": len(test)}
    if min(counts.values()) < int(minimum_domain_rows):
        summary = _summary_row(counts, status="insufficient_domain_rows")
        return _reports(summary, marginal, pd.DataFrame())

    # Keep domains balanced so AUC is not accompanied by a misleading accuracy.
    sample_size = min(len(train), len(test))
    train = train.sample(sample_size, random_state=7301)
    test = test.sample(sample_size, random_state=7302)
    data = pd.concat([train, test], ignore_index=True)
    valid_mask = data[group_column].map(
        lambda value: _stable_fraction(str(value), DRIFT_AUDIT_VERSION) < float(validation_fraction)
    )
    # If the same group names occur in both periods, group hashing prevents the
    # classifier from seeing a symbol in both its fit and validation partitions.
    fit, valid = data.loc[~valid_mask].copy(), data.loc[valid_mask].copy()
    if fit["__domain"].nunique() < 2 or valid["__domain"].nunique() < 2 or len(valid) < 40:
        summary = _summary_row(counts, status="insufficient_group_holdout")
        return _reports(summary, marginal, pd.DataFrame())

    medians = fit[list(features)].median().fillna(0.0)
    x_fit = fit[list(features)].fillna(medians).replace([np.inf, -np.inf], 0.0)
    x_valid = valid[list(features)].fillna(medians).replace([np.inf, -np.inf], 0.0)
    y_fit = fit["__domain"].astype(int).to_numpy()
    y_valid = valid["__domain"].astype(int).to_numpy()
    try:
        from lightgbm import LGBMClassifier

        model = LGBMClassifier(
            n_estimators=120, learning_rate=0.035, num_leaves=15,
            min_child_samples=max(20, len(fit) // 100), subsample=0.85,
            colsample_bytree=0.85, reg_lambda=1.0, random_state=7303,
            n_jobs=1, verbosity=-1,
        )
        model.fit(x_fit, y_fit)
        prediction = model.predict_proba(x_valid)[:, 1]
        importance = np.asarray(model.feature_importances_, dtype=float)
        runtime_model = "lightgbm_classifier"
    except (ImportError, ModuleNotFoundError):
        from sklearn.ensemble import HistGradientBoostingClassifier

        model = HistGradientBoostingClassifier(max_iter=120, learning_rate=.035, max_leaf_nodes=15, random_state=7303)
        model.fit(x_fit, y_fit)
        prediction = model.predict_proba(x_valid)[:, 1]
        importance = np.full(len(features), np.nan)
        runtime_model = "sklearn_hist_gradient_boosting_fallback"

    auc = _auc(y_valid, prediction)
    rng = np.random.default_rng(7304)
    null_auc = np.array([_auc(rng.permutation(y_valid), prediction) for _ in range(int(permutation_samples))])
    p_value = float((1 + np.sum(null_auc >= auc)) / (len(null_auc) + 1))
    status = "material_covariate_drift" if auc >= float(material_auc) and p_value <= 0.05 else "no_material_drift_detected"
    importance_frame = pd.DataFrame({
        "feature": features,
        "split_importance": importance,
        "importance_share": importance / importance.sum() if np.isfinite(importance).all() and importance.sum() > 0 else np.nan,
        "drift_audit_version": DRIFT_AUDIT_VERSION,
    }).sort_values("split_importance", ascending=False, na_position="last")
    summary = _summary_row(
        counts, status=status, heldout_auc=auc, permutation_p_value=p_value,
        material_auc=float(material_auc), fit_rows=len(fit), validation_rows=len(valid),
        runtime_model=runtime_model,
    )
    return _reports(summary, marginal, importance_frame)


def _prepare_domain(frame, features, group_column, domain):
    data = frame[[group_column, *features]].copy()
    data[group_column] = data[group_column].astype(str)
    for feature in features:
        data[feature] = pd.to_numeric(data[feature], errors="coerce")
    data["__domain"] = int(domain)
    return data


def _marginal_drift(train, test, features):
    rows = []
    for feature in features:
        left = train[feature].replace([np.inf, -np.inf], np.nan).dropna()
        right = test[feature].replace([np.inf, -np.inf], np.nan).dropna()
        if len(left) < 20 or len(right) < 20:
            statistic = p_value = standardized_difference = np.nan
        else:
            result = ks_2samp(left, right, alternative="two-sided", method="auto")
            statistic, p_value = float(result.statistic), float(result.pvalue)
            pooled = np.sqrt((left.var(ddof=1) + right.var(ddof=1)) / 2.0)
            standardized_difference = float((right.mean() - left.mean()) / pooled) if pooled > 0 else 0.0
        rows.append({
            "feature": feature, "train_count": len(left), "test_count": len(right),
            "train_mean": left.mean() if len(left) else np.nan,
            "test_mean": right.mean() if len(right) else np.nan,
            "standardized_mean_difference": standardized_difference,
            "ks_statistic": statistic, "ks_p_value": p_value,
        })
    result = pd.DataFrame(rows)
    result["ks_q_value_bh"] = _bh_qvalues(result["ks_p_value"].to_numpy(dtype=float))
    result["marginal_shift_fdr_05"] = result["ks_q_value_bh"].le(.05).fillna(False)
    result["drift_audit_version"] = DRIFT_AUDIT_VERSION
    return result


def _bh_qvalues(values):
    values = np.asarray(values, dtype=float)
    output = np.full(len(values), np.nan)
    valid = np.flatnonzero(np.isfinite(values))
    if not len(valid):
        return output
    ordered = valid[np.argsort(values[valid])]
    adjusted = values[ordered] * len(ordered) / np.arange(1, len(ordered) + 1)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    output[ordered] = np.minimum(adjusted, 1.0)
    return output


def _auc(labels, scores):
    labels = np.asarray(labels, dtype=int)
    scores = pd.Series(np.asarray(scores, dtype=float)).rank(method="average").to_numpy()
    positive, negative = labels == 1, labels == 0
    if not positive.any() or not negative.any():
        return np.nan
    return float((scores[positive].sum() - positive.sum() * (positive.sum() + 1) / 2) / (positive.sum() * negative.sum()))


def _stable_fraction(value, salt):
    integer = int(hashlib.sha256(f"{salt}|{value}".encode("utf-8")).hexdigest()[:16], 16)
    return integer / float(16 ** 16)


def _summary_row(counts, *, status, heldout_auc=np.nan, permutation_p_value=np.nan,
                 material_auc=np.nan, fit_rows=0, validation_rows=0, runtime_model="not_fitted"):
    return pd.DataFrame([{
        "train_row_count": counts["train"], "test_row_count": counts["test"],
        "fit_row_count": fit_rows, "validation_row_count": validation_rows,
        "heldout_domain_auc": heldout_auc, "permutation_p_value": permutation_p_value,
        "material_auc_threshold": material_auc, "evidence_status": status,
        "runtime_model": runtime_model, "target_drift_inference_allowed": False,
        "drift_audit_version": DRIFT_AUDIT_VERSION,
    }])


def _reports(summary, marginal, importance):
    return {
        "governance_failure_lab_adversarial_drift_summary": summary,
        "governance_failure_lab_adversarial_drift_features": marginal,
        "governance_failure_lab_adversarial_drift_importance": importance,
    }
