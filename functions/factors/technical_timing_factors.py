"""Technical timing factors for Factor Judge v2 appeal review."""
from __future__ import annotations

import numpy as np
import pandas as pd


RSI_TIMING_FACTOR_REGISTRY = {
    "rsi_recovery_14": {
        "raw_column": "cand_rsi_recovery_14",
        "module": "rsi",
        "family": "rsi_recovery",
        "allowed_roles": "timing_filter|hold_validation",
    },
    "rsi_overheat_14": {
        "raw_column": "cand_rsi_overheat_14",
        "module": "rsi",
        "family": "rsi_overheat",
        "allowed_roles": "risk_override",
    },
    "rsi_pullback_in_uptrend": {
        "raw_column": "cand_rsi_pullback_in_uptrend",
        "module": "rsi",
        "family": "rsi_pullback",
        "allowed_roles": "timing_filter|hold_validation",
    },
    "rsi_divergence_proxy": {
        "raw_column": "cand_rsi_divergence_proxy",
        "module": "rsi",
        "family": "rsi_divergence",
        "allowed_roles": "timing_filter|risk_override",
    },
    "rsi_slope_5": {
        "raw_column": "cand_rsi_slope_5",
        "module": "rsi",
        "family": "rsi_slope",
        "allowed_roles": "timing_filter|hold_validation",
    },
    "rsi_percentile_252": {
        "raw_column": "cand_rsi_percentile_252",
        "module": "rsi",
        "family": "rsi_percentile",
        "allowed_roles": "risk_override|hold_validation",
    },
}


def append_rsi_timing_factors(
    df: pd.DataFrame,
    *,
    close_col: str = "close_nominal",
    progress_callback=None,
) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    if "symbol" not in df.columns or "date" not in df.columns:
        raise ValueError("RSI timing factors require symbol and date columns")
    close_col = close_col if close_col in df.columns else "close"
    if close_col not in df.columns:
        raise ValueError("RSI timing factors require a close price column")
    frame = df.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.sort_values(["symbol", "date"])
    close = pd.to_numeric(frame[close_col], errors="coerce")
    grouped = frame.groupby("symbol", group_keys=False, sort=False)
    rsi = _rsi(close, frame, 14)
    if progress_callback is not None:
        progress_callback("rsi_series", "computed grouped RSI series")
    rsi_prev = grouped_apply(rsi, frame, 1, "shift")
    close_low_20 = grouped[close_col].transform(lambda s: pd.to_numeric(s, errors="coerce").rolling(20, min_periods=20).min())
    rsi_low_20 = grouped_apply(rsi, frame, 20, "min")
    ma20 = grouped[close_col].transform(lambda s: pd.to_numeric(s, errors="coerce").rolling(20, min_periods=20).mean())
    ma60 = grouped[close_col].transform(lambda s: pd.to_numeric(s, errors="coerce").rolling(60, min_periods=60).mean())
    if progress_callback is not None:
        progress_callback("rsi_windows", "computed RSI rolling windows and moving averages")
    frame["cand_rsi_recovery_14"] = ((rsi_prev <= 35.0) & (rsi > rsi_prev) & (rsi >= 30.0)).astype(float) * (rsi - rsi_prev) / 100.0
    frame["cand_rsi_overheat_14"] = -((rsi - 75.0).clip(lower=0.0) / 25.0)
    frame["cand_rsi_pullback_in_uptrend"] = ((ma20 > ma60) & (rsi < 55.0) & (rsi >= 40.0)).astype(float) * (55.0 - rsi).clip(lower=0.0) / 55.0
    price_new_low = close <= close_low_20
    rsi_not_new_low = rsi > rsi_low_20
    frame["cand_rsi_divergence_proxy"] = (price_new_low & rsi_not_new_low).astype(float) * (rsi - rsi_low_20).clip(lower=0.0) / 100.0
    frame["cand_rsi_slope_5"] = (rsi - grouped_apply(rsi, frame, 5, "shift")) / 5.0
    if progress_callback is not None:
        progress_callback("rsi_signals", "computed RSI recovery, risk, pullback, divergence, and slope signals")
    frame["cand_rsi_percentile_252"] = grouped_apply(rsi, frame, 252, "rank_pct")
    if progress_callback is not None:
        progress_callback("rsi_percentile", "computed RSI 252-day percentiles")
    return frame


def rsi_timing_raw_columns() -> frozenset[str]:
    return frozenset(str(meta["raw_column"]) for meta in RSI_TIMING_FACTOR_REGISTRY.values())


def rsi_timing_registry_rows() -> list[dict]:
    rows = []
    for factor_name, meta in RSI_TIMING_FACTOR_REGISTRY.items():
        rows.append(
            {
                "factor_name": factor_name,
                "module": meta["module"],
                "family": meta["family"],
                "raw_column": meta["raw_column"],
                "direction": "higher_better",
                "allowed_roles": meta["allowed_roles"],
                "candidate_pool": "appeal_rsi_timing",
                "source_file": "functions/factors/technical_timing_factors.py",
            }
        )
    return rows


def _rsi(close: pd.Series, frame: pd.DataFrame, window: int) -> pd.Series:
    ret = close.groupby(frame["symbol"], sort=False).diff()
    gain = ret.clip(lower=0.0)
    loss = -ret.clip(upper=0.0)
    avg_gain = grouped_apply(gain, frame, window, "mean")
    avg_loss = grouped_apply(loss, frame, window, "mean")
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def grouped_apply(values: pd.Series, frame: pd.DataFrame, window: int, op: str) -> pd.Series:
    grouped = values.groupby(frame["symbol"], sort=False)
    if op == "mean":
        return grouped.transform(lambda s: s.rolling(window, min_periods=window).mean())
    if op == "min":
        return grouped.transform(lambda s: s.rolling(window, min_periods=window).min())
    if op == "shift":
        return grouped.shift(window)
    if op == "rank_pct":
        min_periods = max(20, min(window, 60))
        return grouped.transform(
            lambda s: s.rolling(window, min_periods=min_periods).apply(
                lambda values: float(np.mean(values <= values[-1])) if len(values) else np.nan,
                raw=True,
            )
        )
    raise ValueError(f"Unsupported grouped op: {op}")
