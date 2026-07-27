"""Low-memory research Level-1 PIT build from existing local artifacts.

This publisher is deliberately conservative: it never backfills a current
index snapshot before its observed ``asof_date`` and every local-derived table
is marked formal-ineligible until an announcement/revision archive is attached.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import time

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from config import CLEAN_DAILY_PARQUET, CORPORATE_ACTIONS_PARQUET
from functions.data.pit_level1_builder import (
    build_corporate_action_pit,
    build_index_membership_pit,
    build_security_master_pit,
    build_trading_status_pit,
    write_pit_table_atomic,
)
from functions.data.pit_level1_store import DEFAULT_PIT_ROOT, pit_table_path
from functions.investable_universe import INDEX_CONSTITUENTS_PARQUET


def should_preserve_historical_membership(membership_path) -> bool:
    path = Path(membership_path)
    manifest = path.with_suffix(".manifest.json")
    if not path.exists() or not manifest.exists():
        return False
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        source = str(payload.get("provenance", {}).get("source", ""))
    except Exception:
        return False
    return source == "baostock_plus_a500_historical_reconstruction"


def publish_research_pit_level1_low_memory(
    *,
    clean_daily_path=CLEAN_DAILY_PARQUET,
    index_constituents_path=INDEX_CONSTITUENTS_PARQUET,
    corporate_actions_path=CORPORATE_ACTIONS_PARQUET,
    output_root=DEFAULT_PIT_ROOT,
    batch_size: int = 250_000,
    max_runtime_seconds: float = 1800.0,
    progress_callback=None,
) -> dict[str, Path]:
    started = time.monotonic()
    clean_path = Path(clean_daily_path)
    index_path = Path(index_constituents_path)
    actions_path = Path(corporate_actions_path)
    root = Path(output_root)
    if not clean_path.exists():
        raise FileNotFoundError(f"clean daily source is missing: {clean_path}")

    _progress(progress_callback, 5.0, "daily_scan", "building trading-status PIT in bounded batches")
    trading_path, security_source = _stream_daily_tables(
        clean_path,
        root=root,
        batch_size=max(int(batch_size), 1),
        started=started,
        max_runtime_seconds=max_runtime_seconds,
        progress_callback=progress_callback,
    )
    _deadline(started, max_runtime_seconds, "security_master")
    security = build_security_master_pit(
        security_source,
        source_name="tdx_daily_observed_research",
    )
    security_path = write_pit_table_atomic(
        security,
        table_name="security_master_pit",
        root=root,
        formal_eligible=False,
        provenance={
            "source_path": str(clean_path),
            "degradation_flags": ["listing_announcement_time_unavailable", "delisting_chain_unavailable"],
        },
    )

    _progress(progress_callback, 72.0, "index_membership", "preserving historical membership or publishing a dated current snapshot")
    membership_path = pit_table_path("index_membership_pit", root=root)
    preserve_historical = should_preserve_historical_membership(membership_path)
    if not preserve_historical:
        if not index_path.exists():
            raise FileNotFoundError(f"index constituent source is missing: {index_path}")
        index_source = pd.read_parquet(index_path)
        asof = pd.to_datetime(index_source.get("asof_date"), errors="coerce")
        index_source = index_source.assign(
            effective_from=asof,
            known_at=asof,
            source_document_id=(
                index_source.get("source", pd.Series("current_snapshot", index=index_source.index)).astype(str)
                + ":" + asof.astype(str)
            ),
        )
        membership = build_index_membership_pit(
            index_source,
            source_name="current_index_snapshot_research",
        )
        membership_path = write_pit_table_atomic(
            membership,
            table_name="index_membership_pit",
            root=root,
            formal_eligible=False,
            provenance={
                "source_path": str(index_path),
                "degradation_flags": ["historical_add_remove_events_unavailable", "current_snapshot_not_backfilled"],
            },
        )

    _deadline(started, max_runtime_seconds, "corporate_actions")
    _progress(progress_callback, 84.0, "corporate_actions", "publishing conservative action-date-known research table")
    if not actions_path.exists():
        raise FileNotFoundError(f"corporate action source is missing: {actions_path}")
    actions_source = pd.read_parquet(actions_path)
    action_date = pd.to_datetime(actions_source.get("action_date"), errors="coerce")
    actions_source = actions_source.assign(
        ex_date=action_date,
        known_at=action_date,
        source_document_id=(
            actions_source.get("source_name", pd.Series("local_action", index=actions_source.index)).astype(str)
            + ":" + actions_source.index.astype(str)
        ),
        cash_amount=pd.to_numeric(actions_source.get("cash_dividend"), errors="coerce").fillna(0.0),
        share_ratio=(
            pd.to_numeric(actions_source.get("stock_dividend_ratio"), errors="coerce").fillna(0.0)
            + pd.to_numeric(actions_source.get("rights_issue_ratio"), errors="coerce").fillna(0.0)
        ),
    )
    actions = build_corporate_action_pit(
        actions_source,
        source_name="local_corporate_action_research",
    )
    actions_path_out = write_pit_table_atomic(
        actions,
        table_name="corporate_action_pit",
        root=root,
        formal_eligible=False,
        provenance={
            "source_path": str(actions_path),
            "degradation_flags": ["announcement_known_at_unavailable", "action_date_used_conservatively"],
        },
    )
    _progress(progress_callback, 100.0, "complete", "research Level-1 PIT build complete")
    return {
        "security_master_pit": security_path,
        "trading_status_pit": trading_path,
        "index_membership_pit": membership_path,
        "corporate_action_pit": actions_path_out,
    }


def _stream_daily_tables(path, *, root, batch_size, started, max_runtime_seconds, progress_callback):
    parquet = pq.ParquetFile(path)
    output = pit_table_path("trading_status_pit", root=root)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    writer = None
    first_dates: dict[str, pd.Timestamp] = {}
    row_count = 0
    try:
        for batch_index, batch in enumerate(
            parquet.iter_batches(batch_size=batch_size, columns=["date", "symbol", "is_trading", "is_st"])
        ):
            _deadline(started, max_runtime_seconds, f"daily_batch:{batch_index}")
            source = batch.to_pandas()
            source["date"] = pd.to_datetime(source["date"], errors="coerce")
            for symbol, value in source.groupby("symbol", sort=False)["date"].min().items():
                symbol = str(symbol)
                if pd.notna(value) and (symbol not in first_dates or value < first_dates[symbol]):
                    first_dates[symbol] = pd.Timestamp(value)
            normalized = build_trading_status_pit(
                source,
                source_name="tdx_daily_status_research",
            )
            table = pa.Table.from_pandas(normalized, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(temp, table.schema, compression="snappy")
            writer.write_table(table)
            row_count += len(normalized)
            if batch_index % 10 == 0:
                percent = min(68.0, 8.0 + 60.0 * row_count / max(parquet.metadata.num_rows, 1))
                _progress(progress_callback, percent, "daily_scan", f"processed {row_count} daily status rows")
    finally:
        if writer is not None:
            writer.close()
    if writer is None:
        raise ValueError("clean daily source produced no trading-status rows")
    temp.replace(output)
    _write_stream_manifest(
        output,
        table_name="trading_status_pit",
        row_count=row_count,
        provenance={
            "source_path": str(path),
            "formal_eligible": False,
            "degradation_flags": ["exchange_announcement_status_chain_unavailable", "daily_derived_status"],
        },
    )
    security = pd.DataFrame({
        "symbol": list(first_dates),
        "list_date": list(first_dates.values()),
        "delist_date": pd.NaT,
        "security_name": list(first_dates),
    })
    return output, security


def _write_stream_manifest(path: Path, *, table_name: str, row_count: int, provenance: dict):
    manifest = path.with_suffix(".manifest.json")
    temp = manifest.with_suffix(manifest.suffix + ".tmp")
    payload = {
        "table_name": table_name,
        "row_count": int(row_count),
        "formal_eligible": False,
        "provenance": provenance,
        "content_fingerprint": sha256(f"{table_name}|{row_count}|{path.stat().st_size}".encode()).hexdigest(),
    }
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(manifest)


def _deadline(started, maximum, stage):
    if float(maximum) > 0 and time.monotonic() - started > float(maximum):
        raise TimeoutError(f"PIT Level-1 build exceeded max_runtime_seconds at {stage}")


def _progress(callback, percent, step, message):
    if callback is not None:
        callback({"percent": float(percent), "step": str(step), "message": str(message)})
