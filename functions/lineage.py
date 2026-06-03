# -*- coding: utf-8 -*-
"""Column-level lineage and conservative knowledge-time audit."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import FEATURE_LINEAGE_CSV, FEATURE_TIMESTAMP_AUDIT_CSV


LINEAGE_COLUMNS = [
    "column_name",
    "source_table",
    "data_vendor",
    "public_timestamp_rule",
    "vendor_available_timestamp_rule",
    "etl_available_timestamp_rule",
    "knowledge_timestamp_rule",
    "knowledge_lag_assumption",
    "feature_timestamp",
    "price_view",
    "lineage_risk_level",
    "requires_manual_audit",
]

HIGH_RISK_FIELDS = {
    "backward_factor",
    "forward_factor",
    "sector_parent",
    "stabilized_float_cap",
    "event_data",
    "alternative_data",
}


def build_default_feature_lineage(feature_columns) -> pd.DataFrame:
    rows = []
    for column in sorted(set(feature_columns)):
        source_table, vendor, risk, manual = _lineage_source(column)
        rows.append(
            {
                "column_name": column,
                "source_table": source_table,
                "data_vendor": vendor,
                "public_timestamp_rule": "source_specific",
                "vendor_available_timestamp_rule": "source_specific",
                "etl_available_timestamp_rule": "after_local_pipeline_completion",
                "knowledge_timestamp_rule": "daily_bar_t_plus_1_09_00_conservative",
                "knowledge_lag_assumption": "TDX daily bars are not used before T+1 09:00",
                "feature_timestamp": "date_t_plus_1_09_00",
                "price_view": _price_view(column),
                "lineage_risk_level": risk,
                "requires_manual_audit": manual,
            }
        )
    return pd.DataFrame(rows, columns=LINEAGE_COLUMNS)


def audit_feature_timestamps(feature_df: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "feature_timestamp"}
    if not required.issubset(feature_df.columns):
        return pd.DataFrame(
            [{"check": "feature_timestamp_present", "status": "failed", "detail": "missing date or feature_timestamp"}]
        )
    data = feature_df[["date", "feature_timestamp"]].copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["feature_timestamp"] = pd.to_datetime(data["feature_timestamp"], errors="coerce")
    invalid = data["feature_timestamp"].isna() | data["date"].isna() | (data["feature_timestamp"] < data["date"])
    return pd.DataFrame(
        [
            {
                "check": "max_source_timestamp_lte_feature_timestamp",
                "status": "passed" if not invalid.any() else "failed",
                "detail": f"invalid_rows={int(invalid.sum())}",
            },
            {
                "check": "tdx_daily_conservative_knowledge_lag",
                "status": "manual_review_required",
                "detail": "Daily bar use before T+1 09:00 must be rejected by downstream execution policy.",
            },
        ]
    )


def save_lineage_reports(feature_df: pd.DataFrame, feature_columns=None):
    lineage = build_default_feature_lineage(feature_columns or feature_df.columns)
    timestamp_audit = audit_feature_timestamps(feature_df)
    Path(FEATURE_LINEAGE_CSV).parent.mkdir(parents=True, exist_ok=True)
    lineage.to_csv(FEATURE_LINEAGE_CSV, index=False, encoding="utf-8-sig")
    timestamp_audit.to_csv(FEATURE_TIMESTAMP_AUDIT_CSV, index=False, encoding="utf-8-sig")
    return FEATURE_LINEAGE_CSV, FEATURE_TIMESTAMP_AUDIT_CSV


def _lineage_source(column):
    value = str(column)
    if "factor" in value or value in {"backward_factor", "forward_factor"}:
        return "adjustment_factors", "provider_external", "high", True
    if value.startswith("sector_"):
        return "sector_taxonomy", "local_latest_mapping", "high", True
    if "cap" in value:
        return "market_cap_history", "tdx_finance", "high", True
    if value.startswith("future_"):
        return "labels", "derived_future_label", "high", True
    if value in HIGH_RISK_FIELDS:
        return "external_or_derived", "unverified", "high", True
    return "tdx_daily_clean", "tdx_local", "low", False


def _price_view(column):
    value = str(column)
    if value.endswith("_nominal"):
        return "nominal"
    if "_adj_pti" in value:
        return "adjusted_point_in_time"
    return "derived_or_not_applicable"
