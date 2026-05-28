# -*- coding: utf-8 -*-
import pandas as pd

from config import (
    FEATURE_ROBUST_SCALE_EPSILON,
    FEATURE_WINSORIZE_LOWER,
    FEATURE_WINSORIZE_UPPER,
)


def winsorize_cross_section(
    df,
    feature_cols,
    group_col="date",
    lower_q=FEATURE_WINSORIZE_LOWER,
    upper_q=FEATURE_WINSORIZE_UPPER,
):
    frame = df.copy()
    grouped = frame.groupby(group_col)
    for col in feature_cols:
        lower = grouped[col].transform(lambda s: s.quantile(lower_q))
        upper = grouped[col].transform(lambda s: s.quantile(upper_q))
        frame[col] = frame[col].clip(lower=lower, upper=upper)
    return frame


def zscore_cross_section(df, feature_cols, group_col="date"):
    frame = df.copy()
    grouped = frame.groupby(group_col)
    for col in feature_cols:
        mean = grouped[col].transform("mean")
        std = grouped[col].transform("std").replace(0, 1.0).fillna(1.0)
        frame[col] = (frame[col] - mean) / std
    return frame


def robust_scale_cross_section(
    df,
    feature_cols,
    group_col="date",
    epsilon=FEATURE_ROBUST_SCALE_EPSILON,
):
    frame = df.copy()
    grouped = frame.groupby(group_col)
    for col in feature_cols:
        median = grouped[col].transform("median")
        q75 = grouped[col].transform(lambda s: s.quantile(0.75))
        q25 = grouped[col].transform(lambda s: s.quantile(0.25))
        iqr = (q75 - q25).abs().replace(0, epsilon).fillna(epsilon)
        frame[col] = (frame[col] - median) / iqr
    return frame


def neutralize_by_group_and_size(
    df,
    feature_cols,
    group_col="date",
    industry_col="sector_parent",
    size_col="stabilized_float_cap",
):
    frame = df.copy()
    if industry_col not in frame.columns or size_col not in frame.columns:
        for col in feature_cols:
            frame[f"{col}_neutralized"] = frame[col]
        return frame

    def _neutralize_slice(slice_df):
        part = slice_df.copy()
        size_rank = part[size_col].rank(method="average", pct=True)
        for col in feature_cols:
            industry_mean = part.groupby(industry_col)[col].transform("mean")
            size_centered = size_rank - size_rank.mean()
            part[f"{col}_neutralized"] = part[col] - industry_mean - size_centered.fillna(0.0)
        return part

    return (
        frame.groupby(group_col, group_keys=False)
        .apply(_neutralize_slice)
        .reset_index(drop=True)
    )
