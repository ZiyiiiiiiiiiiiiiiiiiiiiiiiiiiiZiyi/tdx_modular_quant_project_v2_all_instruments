"""Normalize free-source snapshots into validated Level-1 PIT tables."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from functions.data.pit_data_contract import PIT_LEVEL1_SCHEMAS, validate_pit_frame
from functions.data.pit_level1_store import DEFAULT_PIT_ROOT, pit_table_path


def build_security_master_pit(source: pd.DataFrame, *, downloaded_at=None, source_name="baostock") -> pd.DataFrame:
    data = source.copy()
    symbol = _column(data, "symbol", "code")
    listed = pd.to_datetime(_column(data, "list_date", "ipoDate", "effective_from"), errors="coerce")
    delisted = pd.to_datetime(_column(data, "delist_date", "outDate", "effective_to"), errors="coerce")
    name = _column(data, "security_name", "code_name", "name").fillna("").astype(str)
    frame = pd.DataFrame({
        "symbol": symbol.astype(str), "effective_from": listed, "effective_to": delisted,
        "known_at": listed, "source": source_name, "source_document_id": data.index.astype(str),
        "downloaded_at": pd.Timestamp(downloaded_at or pd.Timestamp.utcnow()),
        "listing_status": "listed", "security_name": name,
    })
    return _finish(frame, "security_master_pit")


def build_trading_status_pit(source: pd.DataFrame, *, downloaded_at=None, source_name="baostock") -> pd.DataFrame:
    data = source.copy()
    dates = pd.to_datetime(_column(data, "date", "effective_from"), errors="coerce")
    trading = _column(data, "is_trading", "tradestatus").map(_as_bool)
    is_st = _column(data, "is_st", "isST").map(_as_bool)
    frame = pd.DataFrame({
        "symbol": _column(data, "symbol", "code").astype(str),
        "effective_from": dates, "effective_to": dates + pd.Timedelta(days=1), "known_at": dates,
        "source": source_name, "source_document_id": data.index.astype(str),
        "downloaded_at": pd.Timestamp(downloaded_at or pd.Timestamp.utcnow()),
        "is_trading": trading, "is_st": is_st,
        "status_reason": _column(data, "status_reason", default="historical_daily_status").fillna("").astype(str),
    })
    return _finish(frame, "trading_status_pit")


def build_index_membership_pit(source: pd.DataFrame, *, downloaded_at=None, source_name="baostock") -> pd.DataFrame:
    data = source.copy()
    effective = pd.to_datetime(_column(data, "effective_from", "updateDate", "date"), errors="coerce")
    frame = pd.DataFrame({
        "symbol": _column(data, "symbol", "code").astype(str),
        "effective_from": effective, "effective_to": pd.NaT,
        "known_at": pd.to_datetime(_column(data, "known_at", "announcement_date", "updateDate", "date"), errors="coerce"),
        "source": source_name, "source_document_id": _column(data, "source_document_id", default="").astype(str),
        "downloaded_at": pd.Timestamp(downloaded_at or pd.Timestamp.utcnow()),
        "index_code": _column(data, "index_code").astype(str),
        "membership_weight": pd.to_numeric(_column(data, "membership_weight", "weight", default=1.0), errors="coerce"),
    })
    frame = frame.sort_values(["index_code", "symbol", "effective_from", "known_at"])
    frame["effective_to"] = frame.groupby(["index_code", "symbol"], sort=False)["effective_from"].shift(-1)
    return _finish(frame, "index_membership_pit")


def build_corporate_action_pit(source: pd.DataFrame, *, downloaded_at=None, source_name="cninfo") -> pd.DataFrame:
    data = source.copy()
    ex_date = pd.to_datetime(_column(data, "ex_date", "dividOperateDate", "effective_from"), errors="coerce")
    known_at = pd.to_datetime(_column(data, "known_at", "announcement_date", "publish_date"), errors="coerce")
    frame = pd.DataFrame({
        "symbol": _column(data, "symbol", "code").astype(str),
        "effective_from": ex_date, "effective_to": ex_date + pd.Timedelta(days=1), "known_at": known_at,
        "source": source_name, "source_document_id": _column(data, "source_document_id", default="").astype(str),
        "downloaded_at": pd.Timestamp(downloaded_at or pd.Timestamp.utcnow()),
        "action_type": _column(data, "action_type", default="dividend").astype(str), "ex_date": ex_date,
        "cash_amount": pd.to_numeric(_column(data, "cash_amount", "dividCashPsBeforeTax", default=0.0), errors="coerce").fillna(0.0),
        "share_ratio": pd.to_numeric(_column(data, "share_ratio", "dividStocksPs", default=0.0), errors="coerce").fillna(0.0),
    })
    return _finish(frame, "corporate_action_pit")


def write_pit_table_atomic(
    frame: pd.DataFrame,
    *,
    table_name: str,
    root: str | Path = DEFAULT_PIT_ROOT,
    formal_eligible: bool = True,
    provenance: dict | None = None,
) -> Path:
    audit = validate_pit_frame(frame, table_name=table_name)
    failed = audit[~audit["passed"].fillna(False).astype(bool)]
    if not failed.empty:
        raise ValueError(f"Refusing to write invalid {table_name}: {failed.to_dict('records')}")
    path = pit_table_path(table_name, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temp, index=False)
    temp.replace(path)
    manifest_path = path.with_suffix(".manifest.json")
    manifest_temp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    manifest_temp.write_text(
        json.dumps(
            {
                "table_name": table_name,
                "row_count": int(len(frame)),
                "formal_eligible": bool(formal_eligible),
                "provenance": provenance or {},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    manifest_temp.replace(manifest_path)
    return path


def _finish(frame: pd.DataFrame, table_name: str) -> pd.DataFrame:
    data = frame.dropna(subset=["symbol", "effective_from", "known_at"]).copy()
    identity = data.astype(str).agg("|".join, axis=1)
    data["revision_id"] = identity.map(lambda value: sha256(value.encode("utf-8")).hexdigest()[:20])
    for column in PIT_LEVEL1_SCHEMAS[table_name]:
        if column not in data.columns:
            data[column] = pd.NA
    return data[list(PIT_LEVEL1_SCHEMAS[table_name])].drop_duplicates().reset_index(drop=True)


def _column(data: pd.DataFrame, *names: str, default=pd.NA) -> pd.Series:
    for name in names:
        if name in data.columns:
            return data[name]
    return pd.Series(default, index=data.index)


def _as_bool(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}
