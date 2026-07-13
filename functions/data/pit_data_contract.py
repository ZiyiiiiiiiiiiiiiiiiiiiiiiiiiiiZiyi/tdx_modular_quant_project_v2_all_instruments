"""Point-in-time Level-1 schemas, as-of queries, and source registry for A shares."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


PIT_COMMON_COLUMNS = (
    "symbol", "effective_from", "effective_to", "known_at",
    "source", "source_document_id", "revision_id", "downloaded_at",
)

PIT_LEVEL1_SCHEMAS = {
    "security_master_pit": (*PIT_COMMON_COLUMNS, "listing_status", "security_name"),
    "index_membership_pit": (*PIT_COMMON_COLUMNS, "index_code", "membership_weight"),
    "corporate_action_pit": (*PIT_COMMON_COLUMNS, "action_type", "ex_date", "cash_amount", "share_ratio"),
    "trading_status_pit": (*PIT_COMMON_COLUMNS, "is_trading", "is_st", "status_reason"),
}


@dataclass(frozen=True)
class FreePitSource:
    source_id: str
    purpose: str
    endpoint: str
    limitation: str


FREE_PIT_SOURCE_REGISTRY = (
    FreePitSource("baostock", "daily bars and adjustment factors", "https://www.baostock.com", "community data; archive raw responses and cross-check"),
    FreePitSource("cninfo", "announcement timestamps and corporate actions", "https://www.cninfo.com.cn", "document parsing and rate limits required"),
    FreePitSource("sse", "Shanghai listings, status, and announcements", "https://www.sse.com.cn", "exchange-specific; no unified historical snapshot API"),
    FreePitSource("szse", "Shenzhen listings, status, and announcements", "https://www.szse.cn", "exchange-specific; no unified historical snapshot API"),
    FreePitSource("csindex", "index definitions and adjustment announcements", "https://www.csindex.com.cn", "complete historical constituent snapshots may require reconstruction"),
)


def validate_pit_frame(frame: pd.DataFrame, *, table_name: str) -> pd.DataFrame:
    if table_name not in PIT_LEVEL1_SCHEMAS:
        raise KeyError(f"Unknown PIT table: {table_name}")
    required = set(PIT_LEVEL1_SCHEMAS[table_name])
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{table_name} missing required columns: {missing}")
    data = frame.copy()
    for column in ("effective_from", "effective_to", "known_at", "downloaded_at"):
        data[column] = pd.to_datetime(data[column], errors="coerce")
    key_columns = ["symbol", "effective_from", "known_at", "revision_id"]
    duplicate_count = int(data.duplicated(key_columns).sum())
    interval_invalid = data["effective_to"].notna() & data["effective_from"].gt(data["effective_to"])
    known_missing = data["known_at"].isna()
    source_missing = data["source"].fillna("").astype(str).str.strip().eq("")
    return pd.DataFrame([
        {"check": "required_columns", "passed": True, "detail": f"columns={len(data.columns)}"},
        {"check": "unique_revision_key", "passed": duplicate_count == 0, "detail": f"duplicates={duplicate_count}"},
        {"check": "valid_effective_interval", "passed": not interval_invalid.any(), "detail": f"invalid={int(interval_invalid.sum())}"},
        {"check": "known_at_present", "passed": not known_missing.any(), "detail": f"missing={int(known_missing.sum())}"},
        {"check": "source_present", "passed": not source_missing.any(), "detail": f"missing={int(source_missing.sum())}"},
    ])


def pit_asof(frame: pd.DataFrame, *, as_of, effective_on=None) -> pd.DataFrame:
    """Return the latest revision that was knowable at ``as_of``."""
    data = frame.copy()
    as_of_ts = pd.Timestamp(as_of)
    effective_ts = pd.Timestamp(effective_on if effective_on is not None else as_of)
    data["known_at"] = pd.to_datetime(data["known_at"], errors="coerce")
    data["effective_from"] = pd.to_datetime(data["effective_from"], errors="coerce")
    data["effective_to"] = pd.to_datetime(data["effective_to"], errors="coerce")
    eligible = data[
        data["known_at"].le(as_of_ts)
        & data["effective_from"].le(effective_ts)
        & (data["effective_to"].isna() | data["effective_to"].gt(effective_ts))
    ].copy()
    if eligible.empty:
        return eligible
    identity = [column for column in ("symbol", "index_code", "action_type") if column in eligible.columns]
    return eligible.sort_values("known_at").drop_duplicates(identity, keep="last").reset_index(drop=True)


def free_source_registry_frame() -> pd.DataFrame:
    return pd.DataFrame([source.__dict__ for source in FREE_PIT_SOURCE_REGISTRY])
