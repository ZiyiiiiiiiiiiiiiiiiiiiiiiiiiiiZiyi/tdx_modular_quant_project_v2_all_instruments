# -*- coding: utf-8 -*-
import pandas as pd

from config import FACTOR_MIN_COVERAGE_RATIO


FACTOR_STATUS_ORDER = ("stable", "weak", "unstable", "deprecated")


def evaluate_factor_coverage(df, output_columns, min_coverage_ratio=FACTOR_MIN_COVERAGE_RATIO):
    total_rows = len(df)
    rows = []
    for col in output_columns:
        non_null = int(df[col].notna().sum()) if col in df.columns else 0
        coverage_ratio = 0.0 if total_rows == 0 else non_null / total_rows
        status = "stable" if coverage_ratio >= min_coverage_ratio else "weak"
        rows.append(
            {
                "column": col,
                "non_null_rows": non_null,
                "coverage_ratio": coverage_ratio,
                "status": status,
            }
        )
    return pd.DataFrame(rows)


def build_factor_test_report(factor_name, factor_df, output_columns):
    coverage = evaluate_factor_coverage(factor_df, output_columns)
    dominant_status = "deprecated"
    if not coverage.empty:
        dominant_status = coverage["status"].mode().iloc[0]
    return {
        "factor_name": factor_name,
        "row_count": int(len(factor_df)),
        "output_column_count": len(output_columns),
        "dominant_status": dominant_status,
        "coverage": coverage,
    }
