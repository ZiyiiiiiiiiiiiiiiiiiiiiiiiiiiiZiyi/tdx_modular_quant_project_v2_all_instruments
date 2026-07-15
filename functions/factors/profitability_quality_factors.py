"""Profitability-quality factors from explicit PIT TTM inputs."""
from __future__ import annotations

import numpy as np
import pandas as pd

from functions.factors.fundamental_pit_factors import prepare_financial_report_factors


PROFITABILITY_FACTOR_COLUMNS = [
    "roe_ttm_ind_neutral", "roa_ttm_ind_neutral", "gross_margin_ttm",
    "gross_margin_delta", "operating_margin_ttm", "operating_margin_delta",
    "net_margin_stability", "roe_delta_qoq", "roe_vol_neg",
    "deducted_profit_ratio", "piotroski_f_score_proxy",
]


def append_profitability_quality_factors(df: pd.DataFrame) -> pd.DataFrame:
    frame = _prepared(df)
    for column in PROFITABILITY_FACTOR_COLUMNS:
        if column not in frame.columns:
            frame[column] = np.nan
    if "deducted_net_profit_ttm" in frame.columns and "net_profit_ttm" in frame.columns:
        denominator = pd.to_numeric(frame["net_profit_ttm"], errors="coerce").replace(0.0, np.nan)
        frame["deducted_profit_ratio"] = (
            pd.to_numeric(frame["deducted_net_profit_ttm"], errors="coerce") / denominator
        )
    # This remains explicitly a proxy and is emitted only when every component
    # exists. Missing cash flow or margin data must not turn into a false score.
    components = ["net_profit_ttm", "operating_cashflow_ttm", "gross_margin_delta", "roe_delta_qoq"]
    if all(column in frame.columns for column in components):
        complete = frame[components].notna().all(axis=1)
        score = (
            pd.to_numeric(frame["net_profit_ttm"], errors="coerce").gt(0).astype(float)
            + pd.to_numeric(frame["operating_cashflow_ttm"], errors="coerce").gt(0).astype(float)
            + pd.to_numeric(frame["gross_margin_delta"], errors="coerce").gt(0).astype(float)
            + pd.to_numeric(frame["roe_delta_qoq"], errors="coerce").gt(0).astype(float)
        )
        frame["piotroski_f_score_proxy"] = score.where(complete)
    return frame


def _prepared(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    if {"symbol", "known_at", "effective_from", "period_value_basis"}.issubset(df.columns):
        return prepare_financial_report_factors(df)
    return df.copy()
