"""Build research-only PIT Level-2 tables from local TDX finance snapshots."""
from __future__ import annotations

import hashlib
import json
import math
import struct
import time
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd

from functions.data.pit_level2_store import DEFAULT_PIT_LEVEL2_ROOT, validate_pit_level2_frame


TDX_FIELDS = {
    # mootdx's public column list includes report_date at position zero;
    # the binary float payload starts at the following field.
    "total_assets": 39,
    "total_equity": 270,
    "total_equity_fallback": 71,
    "revenue": 229,
    "revenue_fallback": 73,
    "operating_cost": 74,
    "operating_profit": 230,
    "net_profit": 231,
    "deducted_net_profit": 232,
    "operating_cashflow": 233,
    "capex": 113,
    "forecast_yoy_low": 284,
    "forecast_yoy_high": 285,
    "forecast_announcement_date": 312,
    "report_announcement_date": 313,
}


def build_research_pit_level2_from_local_tdx(
    *,
    finance_root="data/raw_external",
    market_cap_path="data/processed/market_cap_history.parquet",
    start_report_date=None,
    end_report_date=None,
    max_files=None,
    symbol_limit=None,
    include_valuation=True,
    max_runtime_seconds=None,
    _started_at=None,
) -> dict[str, pd.DataFrame]:
    paths = sorted(Path(finance_root).glob("gpcw*.zip"))
    if start_report_date:
        paths = [path for path in paths if _filename_date(path) >= pd.Timestamp(start_report_date)]
    if end_report_date:
        paths = [path for path in paths if _filename_date(path) <= pd.Timestamp(end_report_date)]
    if max_files is not None:
        paths = paths[-int(max_files):]
    financial_parts, event_parts = [], []
    started_at = float(_started_at) if _started_at is not None else time.monotonic()
    for path in paths:
        _check_deadline(started_at, max_runtime_seconds, stage=f"parse:{path.name}")
        financial, events = parse_tdx_finance_snapshot(path, symbol_limit=symbol_limit)
        if not financial.empty:
            financial_parts.append(financial)
        if not events.empty:
            event_parts.append(events)
    financial = (
        pd.concat(financial_parts, ignore_index=True).drop_duplicates().reset_index(drop=True)
        if financial_parts else pd.DataFrame()
    )
    events = (
        pd.concat(event_parts, ignore_index=True).drop_duplicates().reset_index(drop=True)
        if event_parts else pd.DataFrame()
    )
    valuation = (
        build_valuation_pit_from_market_cap(market_cap_path, symbol_limit=symbol_limit)
        if include_valuation else pd.DataFrame()
    )
    return {
        "financial_statement_pit": financial,
        "valuation_daily_pit": valuation,
        "corporate_event_pit": events,
    }


def parse_tdx_finance_snapshot(path, *, symbol_limit=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".dat")]
        if not members:
            raise ValueError(f"TDX finance archive has no .dat member: {path}")
        payload = archive.read(members[0])
    header_format, item_format = "<1hI1H3L", "<6s1c1L"
    header_size, item_size = struct.calcsize(header_format), struct.calcsize(item_format)
    header = struct.unpack(header_format, payload[:header_size])
    report_period = pd.Timestamp(str(header[1])).normalize()
    stock_count, report_size = int(header[2]), int(header[4])
    field_count = int(report_size / 4)
    if field_count <= max(TDX_FIELDS.values()):
        raise ValueError(f"TDX finance snapshot has only {field_count} fields: {path}")
    report_format = f"<{field_count}f"
    digest = hashlib.md5(path.read_bytes()).hexdigest()
    downloaded_at = pd.Timestamp(path.stat().st_mtime, unit="s")
    financial_rows, event_rows = [], []
    accepted = 0
    for index in range(stock_count):
        item = payload[header_size + index * item_size:header_size + (index + 1) * item_size]
        if len(item) != item_size:
            continue
        code_raw, _, offset = struct.unpack(item_format, item)
        code = code_raw.decode("ascii", errors="ignore")
        symbol = _symbol(code)
        if symbol is None:
            continue
        record = payload[offset:offset + report_size]
        if len(record) != report_size:
            continue
        values = struct.unpack(report_format, record)
        known_date = _date_value(values[TDX_FIELDS["report_announcement_date"]])
        if pd.isna(known_date):
            continue
        revenue = _first_value(values, "revenue", "revenue_fallback")
        operating_cost = _value(values, TDX_FIELDS["operating_cost"])
        gross_profit = revenue - operating_cost if pd.notna(revenue) and pd.notna(operating_cost) else math.nan
        total_equity = _first_value(values, "total_equity", "total_equity_fallback")
        known_at = known_date + pd.Timedelta(hours=23, minutes=59)
        effective_from = known_date + pd.Timedelta(days=1)
        document_id = f"{path.name}:{symbol}:{digest[:12]}"
        financial_rows.append({
            "symbol": symbol, "report_period": report_period,
            "statement_type": "consolidated", "period_value_basis": "ytd",
            "known_at": known_at, "effective_from": effective_from,
            "source": "tdx_gpcw_current_snapshot_research_only",
            "source_document_id": document_id, "revision_id": digest[:16],
            "downloaded_at": downloaded_at, "revenue": revenue,
            "net_profit": _value(values, TDX_FIELDS["net_profit"]),
            "deducted_net_profit": _value(values, TDX_FIELDS["deducted_net_profit"]),
            "gross_profit": gross_profit,
            "operating_profit": _value(values, TDX_FIELDS["operating_profit"]),
            "operating_cashflow": _value(values, TDX_FIELDS["operating_cashflow"]),
            "capex": _value(values, TDX_FIELDS["capex"]),
            "total_assets": _value(values, TDX_FIELDS["total_assets"]),
            "total_equity": total_equity, "industry": "",
        })
        forecast_date = _date_value(values[TDX_FIELDS["forecast_announcement_date"]])
        low = _value(values, TDX_FIELDS["forecast_yoy_low"])
        high = _value(values, TDX_FIELDS["forecast_yoy_high"])
        midpoint = _mean_available(low, high)
        if pd.notna(forecast_date) and pd.notna(midpoint):
            event_known_at = forecast_date + pd.Timedelta(hours=23, minutes=59)
            event_rows.append({
                "symbol": symbol, "event_id": f"forecast:{symbol}:{report_period:%Y%m%d}",
                "event_type": "earnings_forecast", "event_stage": "announced",
                "announcement_time": event_known_at, "known_at": event_known_at,
                "effective_from": forecast_date + pd.Timedelta(days=1),
                "source": "tdx_gpcw_current_snapshot_research_only",
                "source_document_id": document_id, "revision_id": digest[:16],
                "downloaded_at": downloaded_at,
                "direction": "positive" if midpoint >= 0.0 else "negative",
                "strength": min(abs(float(midpoint)) / 100.0, 5.0),
                "cancelled": False, "revision_of": "",
            })
        accepted += 1
        if symbol_limit is not None and accepted >= int(symbol_limit):
            break
    return pd.DataFrame(financial_rows), pd.DataFrame(event_rows)


def build_valuation_pit_from_market_cap(path, *, symbol_limit=None) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    columns = ["symbol", "date", "stabilized_total_cap", "stabilized_float_cap", "source_name"]
    data = pd.read_parquet(path, columns=columns)
    if symbol_limit is not None:
        symbols = set(data["symbol"].drop_duplicates().sort_values().head(int(symbol_limit)))
        data = data[data["symbol"].isin(symbols)].copy()
    return _valuation_frame(data, source_mtime=path.stat().st_mtime)


def _valuation_frame(data: pd.DataFrame, *, source_mtime) -> pd.DataFrame:
    dates = pd.to_datetime(data["date"], errors="coerce").dt.normalize()
    return pd.DataFrame({
        "symbol": data["symbol"].astype(str), "valuation_date": dates,
        "known_at": dates + pd.Timedelta(hours=15), "effective_from": dates,
        "source": data["source_name"].fillna("tdx_market_cap_history").astype(str),
        "source_document_id": data["symbol"].astype(str) + ":" + dates.dt.strftime("%Y%m%d"),
        "revision_id": "1", "downloaded_at": pd.Timestamp(source_mtime, unit="s"),
        "market_cap": pd.to_numeric(data["stabilized_total_cap"], errors="coerce"),
        "float_cap": pd.to_numeric(data["stabilized_float_cap"], errors="coerce"),
        "pe_ttm": math.nan, "pb_mrq": math.nan,
    })


def publish_research_pit_level2_low_memory(
    *,
    finance_root="data/raw_external",
    market_cap_path="data/processed/market_cap_history.parquet",
    root=DEFAULT_PIT_LEVEL2_ROOT,
    batch_size=100_000,
    progress_callback=None,
    max_runtime_seconds=1800.0,
) -> dict[str, Path]:
    """Publish local research tables while streaming the 9M-row valuation input."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    def progress(percent, step, message, detail=""):
        if progress_callback:
            progress_callback({
                "percent": float(percent), "step": step,
                "message": message, "detail": detail,
            })

    started_at = time.monotonic()
    progress(5.0, "parse_financial", "parsing local TDX finance snapshots")
    tables = build_research_pit_level2_from_local_tdx(
        finance_root=finance_root,
        market_cap_path=market_cap_path,
        include_valuation=False,
        max_runtime_seconds=max_runtime_seconds,
        _started_at=started_at,
    )
    output = Path(root)
    output.mkdir(parents=True, exist_ok=True)
    saved = publish_research_pit_level2(tables, root=output)
    source = Path(market_cap_path)
    if not source.exists():
        raise FileNotFoundError(f"Market-cap history unavailable: {source}")
    progress(45.0, "valuation_stream", "streaming daily valuation PIT table")
    parquet = pq.ParquetFile(source)
    source_columns = ["symbol", "date", "stabilized_total_cap", "stabilized_float_cap", "source_name"]
    target = output / "valuation_daily_pit.parquet"
    temporary = output / f"valuation_daily_pit.building.{datetime.now():%Y%m%d%H%M%S}.parquet"
    writer = None
    row_count = 0
    try:
        for batch_index, batch in enumerate(
            parquet.iter_batches(batch_size=int(batch_size), columns=source_columns), start=1
        ):
            _check_deadline(started_at, max_runtime_seconds, stage=f"valuation_batch:{batch_index}")
            frame = _valuation_frame(batch.to_pandas(), source_mtime=source.stat().st_mtime)
            audit = validate_pit_level2_frame(frame, table_name="valuation_daily_pit")
            failed = audit[~audit["passed"].fillna(False).astype(bool)]
            if not failed.empty:
                raise ValueError(f"Invalid valuation batch {batch_index}: {failed.to_dict('records')}")
            table = pa.Table.from_pandas(frame, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(temporary, table.schema, compression="snappy")
            writer.write_table(table)
            row_count += len(frame)
            if batch_index % 10 == 0:
                progress(
                    min(92.0, 45.0 + row_count / max(parquet.metadata.num_rows, 1) * 47.0),
                    "valuation_stream", "streaming daily valuation PIT table",
                    f"rows={row_count}/{parquet.metadata.num_rows}",
                )
    finally:
        if writer is not None:
            writer.close()
    if row_count == 0:
        raise ValueError("Market-cap history produced no valuation PIT rows")
    temporary.replace(target)
    _write_research_manifest(target, table_name="valuation_daily_pit", row_count=row_count)
    saved["valuation_daily_pit"] = target
    progress(100.0, "complete", "PIT Level-2 research tables published", f"valuation_rows={row_count}")
    return saved


def publish_research_pit_level2(tables: dict[str, pd.DataFrame], *, root=DEFAULT_PIT_LEVEL2_ROOT) -> dict[str, Path]:
    output = Path(root)
    output.mkdir(parents=True, exist_ok=True)
    saved = {}
    for table_name, frame in tables.items():
        if frame is None or frame.empty:
            continue
        audit = validate_pit_level2_frame(frame, table_name=table_name)
        failed = audit[~audit["passed"].fillna(False).astype(bool)]
        if not failed.empty:
            raise ValueError(f"Cannot publish invalid {table_name}: {failed.to_dict('records')}")
        path = output / f"{table_name}.parquet"
        frame.to_parquet(path, index=False)
        _write_research_manifest(path, table_name=table_name, row_count=len(frame))
        saved[table_name] = path
    return saved


def _write_research_manifest(path: Path, *, table_name: str, row_count: int) -> None:
    manifest = {
        "table_name": table_name, "row_count": int(row_count),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "formal_eligible": False,
        "degradation_flags": ["historical_revision_chain_unavailable", "current_snapshot_research_only"],
    }
    path.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _filename_date(path: Path) -> pd.Timestamp:
    digits = "".join(character for character in path.stem if character.isdigit())
    return pd.Timestamp(digits[-8:])


def _symbol(code: str):
    if code.startswith("6"):
        return f"sh{code}"
    if code.startswith(("0", "3")):
        return f"sz{code}"
    return None


def _value(values, index):
    value = float(values[index])
    return value if math.isfinite(value) and abs(value) < 1e30 else math.nan


def _first_value(values, *keys):
    for key in keys:
        value = _value(values, TDX_FIELDS[key])
        if pd.notna(value):
            return value
    return math.nan


def _date_value(value):
    numeric = _value((value,), 0)
    if pd.isna(numeric):
        return pd.NaT
    text = str(int(numeric))
    if len(text) == 6:
        text = "20" + text
    if len(text) != 8:
        return pd.NaT
    return pd.to_datetime(text, format="%Y%m%d", errors="coerce")


def _mean_available(left, right):
    values = [value for value in (left, right) if pd.notna(value)]
    return float(sum(values) / len(values)) if values else math.nan


def _check_deadline(started_at: float, max_runtime_seconds, *, stage: str) -> None:
    if max_runtime_seconds is None:
        return
    limit = float(max_runtime_seconds)
    if limit <= 0.0:
        raise ValueError("max_runtime_seconds must be positive")
    elapsed = time.monotonic() - float(started_at)
    if elapsed > limit:
        raise TimeoutError(
            f"PIT Level-2 build exceeded max_runtime_seconds={limit:.1f} "
            f"at stage={stage}; elapsed={elapsed:.1f}s"
        )
