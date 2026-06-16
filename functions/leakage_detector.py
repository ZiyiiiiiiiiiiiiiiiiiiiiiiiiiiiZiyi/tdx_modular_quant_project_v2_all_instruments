# -*- coding: utf-8 -*-
"""
Data leakage detection for feature engineering and ML training.

Checks for look-ahead bias:
1. Features at time t must NOT use data from t+1 or later.
2. Labels are allowed to use future data (they ARE the target).
3. ML training must respect train/test temporal boundaries.
4. Rolling/shifted features must use only past data.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

from functions.pricing.feature_leakage_audit import (
    find_forbidden_feature_columns,
    find_future_like_columns,
)


@dataclass
class LeakageReport:
    """Result of a data leakage audit."""
    n_features_checked: int
    n_labels_checked: int
    future_like_columns: list[str]
    forbidden_feature_columns: list[str]
    temporal_violations: list[dict]
    ml_split_violations: list[dict]
    is_clean: bool

    def to_dict(self) -> dict:
        return {
            "n_features_checked": self.n_features_checked,
            "n_labels_checked": self.n_labels_checked,
            "future_like_columns": self.future_like_columns,
            "forbidden_feature_columns": self.forbidden_feature_columns,
            "temporal_violations": self.temporal_violations,
            "ml_split_violations": self.ml_split_violations,
            "is_clean": self.is_clean,
        }


def detect_future_data_in_features(
    df: pd.DataFrame,
    feature_columns: list[str],
    label_columns: list[str] | None = None,
    date_col: str = "date",
    symbol_col: str = "symbol",
) -> LeakageReport:
    """
    Check if any feature column at time t contains data from t+1 or later.

    Methodology:
    - For each numeric feature, compute correlation between
      feature[t] and close[t+1]. If correlation is suspiciously high
      (close to 1.0), the feature likely contains future data.
    - Also check column names for future-looking prefixes.
    - Check that rolling/shifted features don't shift in the wrong direction.
    """
    label_columns = label_columns or [c for c in df.columns if c.startswith("future_ret_")]
    feature_columns = [c for c in feature_columns if c not in label_columns]

    # 1. Column name checks
    future_like = find_future_like_columns(feature_columns)
    forbidden = find_forbidden_feature_columns(feature_columns)

    # 2. Statistical leakage detection
    temporal_violations = []
    if date_col in df.columns and symbol_col in df.columns:
        close_col = "close" if "close" in df.columns else "close_nominal"
        if close_col in df.columns:
            for col in feature_columns:
                if col in {date_col, symbol_col, close_col, "open", "high", "low", "volume", "amount"}:
                    continue
                if col not in df.columns:
                    continue
                if not pd.api.types.is_numeric_dtype(df[col]):
                    continue
                try:
                    violation = _check_feature_leakage_statistically(
                        df, col, close_col, date_col, symbol_col
                    )
                    if violation:
                        temporal_violations.append(violation)
                except Exception:
                    pass

    # 3. Check for shift direction issues
    shift_violations = _check_shift_direction(df, feature_columns, date_col, symbol_col)
    temporal_violations.extend(shift_violations)

    n_features = len(feature_columns)
    n_labels = len(label_columns)
    is_clean = not (future_like or forbidden or temporal_violations)

    return LeakageReport(
        n_features_checked=n_features,
        n_labels_checked=n_labels,
        future_like_columns=future_like,
        forbidden_feature_columns=forbidden,
        temporal_violations=temporal_violations,
        ml_split_violations=[],
        is_clean=is_clean,
    )


def _check_feature_leakage_statistically(
    df: pd.DataFrame,
    feature_col: str,
    close_col: str,
    date_col: str,
    symbol_col: str,
) -> dict | None:
    """
    Check if feature[t] is suspiciously correlated with close[t+1].

    A high correlation (>0.99) suggests the feature contains tomorrow's price.
    """
    sample_symbols = df[symbol_col].drop_duplicates().head(20)
    sample = df[df[symbol_col].isin(sample_symbols)].copy()
    sample = sample.sort_values([symbol_col, date_col])

    # Compute close[t+1]
    sample["close_next"] = sample.groupby(symbol_col)[close_col].shift(-1)
    subset = sample[[feature_col, "close_next"]].dropna()

    if len(subset) < 100:
        return None

    corr = subset[feature_col].corr(subset["close_next"])
    if pd.isna(corr):
        return None

    if abs(corr) > 0.99:
        return {
            "type": "statistical_leakage",
            "feature": feature_col,
            "correlation_with_close_next": float(corr),
            "sample_size": len(subset),
            "severity": "HIGH",
            "message": (
                f"{feature_col} has correlation {corr:.4f} with close[t+1]. "
                f"This strongly suggests look-ahead bias."
            ),
        }
    elif abs(corr) > 0.95:
        return {
            "type": "statistical_leakage",
            "feature": feature_col,
            "correlation_with_close_next": float(corr),
            "sample_size": len(subset),
            "severity": "MEDIUM",
            "message": (
                f"{feature_col} has correlation {corr:.4f} with close[t+1]. "
                f"Review for possible look-ahead bias."
            ),
        }
    return None


def _check_shift_direction(
    df: pd.DataFrame,
    feature_columns: list[str],
    date_col: str,
    symbol_col: str,
) -> list[dict]:
    """
    Check for features that shift in the wrong direction.
    A feature like `close.shift(-1)` at time t would contain t+1 data.
    """
    violations = []
    # Look for columns that are perfect copies of future values
    close_col = "close" if "close" in df.columns else "close_nominal"
    if close_col not in df.columns:
        return violations

    for col in feature_columns:
        if col == close_col:
            continue
        if col not in df.columns:
            continue
        if not pd.api.types.is_numeric_dtype(df[col]):
            continue

        # Check if feature equals close shifted by various amounts
        sample = df.head(1000)
        for shift in [-1, -2, -5]:
            shifted = sample.groupby(symbol_col)[close_col].shift(shift)
            match = sample[col].equals(shifted)
            if match:
                violations.append({
                    "type": "shift_direction",
                    "feature": col,
                    "shift": shift,
                    "severity": "HIGH",
                    "message": (
                        f"{col} is exactly equal to close.shift({shift}). "
                        f"This means it uses future data at time t."
                    ),
                })
    return violations


def detect_ml_training_leakage(
    train_dates: pd.Series,
    test_dates: pd.Series,
    purge_days: int = 5,
    embargo_days: int = 5,
) -> list[dict]:
    """
    Check if ML train/test split has proper temporal separation.

    Parameters
    ----------
    train_dates : pd.Series
        Dates used for training.
    test_dates : pd.Series
        Dates used for testing/prediction.
    purge_days : int
        Minimum gap between last train date and first test date.
    embargo_days : int
        Additional embargo period after training.
    """
    violations = []
    train_max = pd.to_datetime(train_dates).max()
    test_min = pd.to_datetime(test_dates).min()

    if pd.isna(train_max) or pd.isna(test_min):
        return violations

    actual_gap = (test_min - train_max).days
    required_gap = purge_days + embargo_days

    if actual_gap < 0:
        violations.append({
            "type": "temporal_overlap",
            "train_end": str(train_max.date()),
            "test_start": str(test_min.date()),
            "actual_gap_days": actual_gap,
            "severity": "CRITICAL",
            "message": (
                f"Test data starts BEFORE training ends! "
                f"Train end={train_max.date()}, Test start={test_min.date()}. "
                f"Gap={actual_gap} days."
            ),
        })
    elif actual_gap < required_gap:
        violations.append({
            "type": "insufficient_purge",
            "train_end": str(train_max.date()),
            "test_start": str(test_min.date()),
            "actual_gap_days": actual_gap,
            "required_gap_days": required_gap,
            "severity": "HIGH",
            "message": (
                f"Insufficient purge/embargo between train and test. "
                f"Actual gap={actual_gap} days, required={required_gap} days."
            ),
        })

    return violations


def detect_feature_label_alignment(
    df: pd.DataFrame,
    feature_columns: list[str],
    label_column: str = "future_ret_5",
    date_col: str = "date",
    symbol_col: str = "symbol",
) -> list[dict]:
    """
    Verify that feature values at time t align with labels at time t,
    not t+1 or t-1.

    This checks that when we use features from row i to predict label[i],
    the features are from the same date as the label's base date.
    """
    violations = []
    if label_column not in df.columns:
        return violations

    close_col = "close" if "close" in df.columns else "close_nominal"
    if close_col not in df.columns:
        return violations

    # Check: label at row i should be based on close[i], not close[i+1]
    # future_ret_5 = close[i+5] / close[i] - 1
    # If we accidentally shifted labels, features at i would predict label at i-1
    sample = df.head(1000).copy()
    sample = sample.sort_values([symbol_col, date_col])

    # Verify label is computed correctly
    for sym in sample[symbol_col].drop_duplicates().head(5):
        sym_data = sample[sample[symbol_col] == sym].copy()
        if len(sym_data) < 10:
            continue
        close = sym_data[close_col].values
        label_vals = sym_data[label_column].values
        # Manually compute future_ret_5
        expected = np.full(len(close), np.nan)
        for i in range(len(close) - 5):
            if close[i] != 0:
                expected[i] = close[i + 5] / close[i] - 1
        # Compare
        valid_mask = ~np.isnan(expected) & ~np.isnan(label_vals)
        if valid_mask.sum() > 0:
            max_diff = np.max(np.abs(expected[valid_mask] - label_vals[valid_mask]))
            if max_diff > 1e-6:
                violations.append({
                    "type": "label_alignment",
                    "symbol": sym,
                    "max_difference": float(max_diff),
                    "severity": "CRITICAL",
                    "message": (
                        f"Label {label_column} for {sym} does not match "
                        f"close[i+5]/close[i]-1. Max diff={max_diff:.6f}. "
                        f"Labels may be misaligned."
                    ),
                })
    return violations


def run_full_leakage_audit(
    feature_df: pd.DataFrame,
    feature_columns: list[str],
    label_columns: list[str] | None = None,
    ml_train_dates: pd.Series | None = None,
    ml_test_dates: pd.Series | None = None,
    purge_days: int = 5,
) -> dict:
    """
    Run the complete data leakage audit.

    Returns a dict with all findings.
    """
    label_columns = label_columns or [c for c in feature_df.columns if c.startswith("future_ret_")]

    # Feature-level leakage
    feature_report = detect_future_data_in_features(
        feature_df, feature_columns, label_columns
    )

    # ML training leakage
    ml_violations = []
    if ml_train_dates is not None and ml_test_dates is not None:
        ml_violations = detect_ml_training_leakage(
            ml_train_dates, ml_test_dates, purge_days=purge_days
        )

    # Label alignment
    label_violations = detect_feature_label_alignment(
        feature_df, feature_columns
    )

    all_violations = (
        feature_report.temporal_violations
        + ml_violations
        + label_violations
    )
    critical = [v for v in all_violations if v.get("severity") == "CRITICAL"]
    high = [v for v in all_violations if v.get("severity") == "HIGH"]

    return {
        "feature_report": feature_report.to_dict(),
        "ml_split_violations": ml_violations,
        "label_alignment_violations": label_violations,
        "total_violations": len(all_violations),
        "critical_violations": len(critical),
        "high_violations": len(high),
        "is_clean": feature_report.is_clean and not ml_violations and not label_violations,
        "summary": _build_leakage_summary(all_violations),
    }


def _build_leakage_summary(violations: list[dict]) -> str:
    if not violations:
        return "No data leakage detected."
    lines = [f"Found {len(violations)} potential leakage issue(s):"]
    for v in violations:
        lines.append(f"  [{v.get('severity', 'UNKNOWN')}] {v.get('message', str(v))}")
    return "\n".join(lines)


def leakage_audit_report(result: dict) -> str:
    """Generate markdown report for leakage audit."""
    lines = [
        "# Data Leakage Audit Report",
        "",
        f"- Features checked: {result['feature_report']['n_features_checked']}",
        f"- Labels checked: {result['feature_report']['n_labels_checked']}",
        f"- Total violations: {result['total_violations']}",
        f"- Critical: {result['critical_violations']}",
        f"- High: {result['high_violations']}",
        f"- Clean: {result['is_clean']}",
        "",
    ]

    fr = result["feature_report"]
    if fr["future_like_columns"]:
        lines.append("## Future-Like Column Names")
        for col in fr["future_like_columns"]:
            lines.append(f"- `{col}`")
        lines.append("")

    if fr["forbidden_feature_columns"]:
        lines.append("## Forbidden Feature Columns")
        for col in fr["forbidden_feature_columns"]:
            lines.append(f"- `{col}`")
        lines.append("")

    if fr["temporal_violations"]:
        lines.append("## Temporal Violations")
        for v in fr["temporal_violations"]:
            lines.append(f"- **{v['severity']}**: {v['message']}")
        lines.append("")

    if result["ml_split_violations"]:
        lines.append("## ML Training Split Violations")
        for v in result["ml_split_violations"]:
            lines.append(f"- **{v['severity']}**: {v['message']}")
        lines.append("")

    if result["label_alignment_violations"]:
        lines.append("## Label Alignment Violations")
        for v in result["label_alignment_violations"]:
            lines.append(f"- **{v['severity']}**: {v['message']}")
        lines.append("")

    lines.append(f"## Summary\n{result['summary']}")
    return "\n".join(lines)
