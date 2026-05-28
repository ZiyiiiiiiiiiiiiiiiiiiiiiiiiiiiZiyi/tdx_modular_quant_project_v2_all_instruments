# -*- coding: utf-8 -*-
import pandas as pd


def build_feature_coverage_report(df, feature_cols):
    rows = []
    total_rows = len(df)
    for col in feature_cols:
        non_null = int(df[col].notna().sum())
        rows.append(
            {
                "feature": col,
                "non_null_rows": non_null,
                "coverage_ratio": 0.0 if total_rows == 0 else non_null / total_rows,
            }
        )
    return pd.DataFrame(rows)


def build_feature_distribution_report(df, feature_cols):
    rows = []
    for col in feature_cols:
        series = pd.to_numeric(df[col], errors="coerce")
        rows.append(
            {
                "feature": col,
                "mean": float(series.mean()) if series.notna().any() else None,
                "std": float(series.std()) if series.notna().any() else None,
                "median": float(series.median()) if series.notna().any() else None,
                "min": float(series.min()) if series.notna().any() else None,
                "max": float(series.max()) if series.notna().any() else None,
            }
        )
    return pd.DataFrame(rows)


def build_feature_correlation_report(df, feature_cols):
    if not feature_cols:
        return pd.DataFrame()
    corr = df[feature_cols].corr(numeric_only=True)
    corr.index.name = "feature"
    return corr.reset_index()


def build_feature_stability_report(df, feature_cols, group_col="date"):
    rows = []
    grouped = df.groupby(group_col)
    for col in feature_cols:
        group_means = grouped[col].mean()
        rows.append(
            {
                "feature": col,
                "time_mean_mean": float(group_means.mean()) if not group_means.empty else None,
                "time_mean_std": float(group_means.std()) if not group_means.empty else None,
                "date_count": int(group_means.shape[0]),
            }
        )
    return pd.DataFrame(rows)
