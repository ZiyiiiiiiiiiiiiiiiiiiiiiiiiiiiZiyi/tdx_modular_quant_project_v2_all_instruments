"""Materialized feature cache for factor-cabinet governance runs."""
from __future__ import annotations

import json
import gc
import os
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import FEATURE_DAILY_PARQUET, GOVERNANCE_PRE_SCREEN_FACTOR_CACHE_LOOKBACK_DAYS
from functions.decision_council.candidate_factor_cache import (
    FACTOR_CACHE_INDEX_COLUMNS,
    candidate_factor_source_columns,
    pre_screen_candidate_raw_columns,
)
from functions.decision_council.factor_source import (
    FACTOR_CABINET_PASSTHROUGH_COLUMNS,
    FACTOR_SOURCE_LEGACY,
    FactorSourceSpec,
    is_factor_cabinet_runtime_column,
    resolve_factor_source,
)
from functions.factors.factor_candidate_pool import append_candidate_factors
from functions.factors.technical_timing_factors import append_rsi_timing_factors, rsi_timing_raw_columns
from functions.factors.pit_factor_materialization import attach_pit_level2_factors
from functions.factors.pit_factor_registry import pit_factor_raw_columns
from functions.pipeline_cache import file_fingerprint


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FACTOR_CABINET_FEATURE_CACHE_ROOT = PROJECT_ROOT / "results" / "factor_cabinet_feature_cache"


def factor_cabinet_feature_cache_paths(
    factor_cabinet_run_id: str,
    start_date,
    end_date,
    *,
    root: str | Path = FACTOR_CABINET_FEATURE_CACHE_ROOT,
) -> tuple[Path, Path]:
    start = pd.Timestamp(start_date).strftime("%Y%m%d")
    end = pd.Timestamp(end_date).strftime("%Y%m%d")
    base = Path(root) / str(factor_cabinet_run_id)
    stem = f"factor_cabinet_features_{start}_{end}"
    return base / f"{stem}.parquet", base / f"{stem}.manifest.json"


def build_factor_cabinet_feature_cache(
    *,
    factor_source: str,
    factor_cabinet_run_id: str = "",
    factor_cabinet_path: str = "",
    start_date,
    end_date,
    feature_path: Path = FEATURE_DAILY_PARQUET,
    progress_callback=None,
) -> tuple[Path, Path]:
    spec = resolve_factor_source(
        factor_source=factor_source,
        factor_cabinet_run_id=factor_cabinet_run_id,
        factor_cabinet_path=factor_cabinet_path,
    )
    if not spec.uses_factor_cabinet:
        raise ValueError("factor_cabinet feature cache requires latest_factor_cabinet or selected_factor_cabinet")
    raw_columns = _factor_cabinet_raw_columns(spec)
    if not raw_columns:
        raise ValueError(f"factor_cabinet {spec.factor_cabinet_run_id} has no generated candidate columns")

    requested_start = pd.Timestamp(start_date)
    requested_end = pd.Timestamp(end_date)
    build_start = requested_start - pd.Timedelta(days=int(GOVERNANCE_PRE_SCREEN_FACTOR_CACHE_LOOKBACK_DAYS) + 7)
    output_path, manifest_path = factor_cabinet_feature_cache_paths(
        spec.factor_cabinet_run_id,
        requested_start,
        requested_end,
    )
    _emit_progress(
        progress_callback,
        percent=5.0,
        step="resolve_factor_cabinet",
        message="resolved factor_cabinet feature cache request",
        detail=f"run_id={spec.factor_cabinet_run_id}, raw_columns={len(raw_columns)}",
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    parquet_path, base_manifest_path, build_stats = _build_factor_cabinet_feature_cache_chunked(
        build_start=build_start,
        requested_start=requested_start,
        requested_end=requested_end,
        raw_columns=raw_columns,
        feature_path=Path(feature_path),
        output_path=output_path,
        progress_callback=progress_callback,
    )
    manifest = {
        "artifact_type": "factor_cabinet_feature_cache",
        "cache_version": "factor_cabinet_feature_cache_v2_chunked",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "date_min": build_stats["date_min"],
        "date_max": build_stats["date_max"],
        "usable_date_min": requested_start.strftime("%Y-%m-%d"),
        "lookback_days": int(GOVERNANCE_PRE_SCREEN_FACTOR_CACHE_LOOKBACK_DAYS) + 7,
        "alpha_models": list(spec.alpha_models),
        "raw_columns": list(raw_columns),
        "row_count": int(build_stats["row_count"]),
        "symbol_count": int(build_stats["symbol_count"]),
        "symbol_scope": "all",
        "parquet_path": str(parquet_path),
        "feature_input": file_fingerprint(feature_path),
        "chunk_count": int(build_stats["chunk_count"]),
        "chunk_mode": "fixed_45_calendar_days",
        "storage_layout": build_stats.get("storage_layout", "single_file"),
    }
    manifest.update(
        {
            "factor_source": spec.factor_source,
            "factor_cabinet_run_id": spec.factor_cabinet_run_id,
            "factor_cabinet_path": spec.factor_cabinet_path,
            "cabinet_manifest_hash": spec.cabinet_manifest_hash,
            "factor_count": spec.factor_count,
            "requested_date_min": requested_start.strftime("%Y-%m-%d"),
            "requested_date_max": requested_end.strftime("%Y-%m-%d"),
        }
    )
    _write_manifest_atomic(base_manifest_path, manifest)
    _emit_progress(
        progress_callback,
        percent=100.0,
        step="complete",
        message="factor_cabinet feature cache built",
        detail=f"path={parquet_path}",
    )
    return parquet_path, base_manifest_path


def _build_factor_cabinet_feature_cache_chunked(
    *,
    build_start,
    requested_start,
    requested_end,
    raw_columns: tuple[str, ...],
    feature_path: Path,
    output_path: Path,
    progress_callback=None,
) -> tuple[Path, Path, dict]:
    import pyarrow as pa
    import pyarrow.parquet as pq

    available_columns = set(pq.read_schema(feature_path).names)
    columns = [column for column in candidate_factor_source_columns() if column in available_columns]
    if (
        set(raw_columns) & set(pit_factor_raw_columns())
        and "sector_parent" in available_columns
        and "sector_parent" not in columns
    ):
        columns.append("sector_parent")
    # Approved appeal factors already exist in the base feature parquet as
    # score_* columns. Read those columns directly while generated cand_ fields
    # continue through append_candidate_factors below.
    columns.extend(
        column for column in raw_columns
        if column in FACTOR_CABINET_PASSTHROUGH_COLUMNS
        and column in available_columns
        and column not in columns
    )
    filters_base = []
    if "instrument_type" in available_columns:
        filters_base.append(("instrument_type", "in", ["stock", "etf_fund"]))

    chunks = list(_iter_fixed_day_chunks(requested_start, requested_end, days=45))
    dataset_path = output_path.with_name(
        f"{output_path.stem}_parts_{os.getpid()}_{time.time_ns()}.parquet"
    )
    dataset_path.mkdir(parents=True, exist_ok=False)
    row_count = 0
    symbol_values: set[str] = set()
    written_date_min = None
    written_date_max = None
    manifest_path = output_path.with_suffix(".manifest.json")
    for index, (chunk_start, chunk_end) in enumerate(chunks, start=1):
        read_start = max(pd.Timestamp(build_start), chunk_start - pd.Timedelta(days=int(GOVERNANCE_PRE_SCREEN_FACTOR_CACHE_LOOKBACK_DAYS) + 7))
        chunk_base = 5.0 + (index - 1) / max(len(chunks), 1) * 90.0
        chunk_span = 90.0 / max(len(chunks), 1)
        _emit_progress(
            progress_callback,
            percent=chunk_base,
            step="chunk_read",
            message="reading factor_cabinet feature cache chunk",
            detail=f"chunk={index}/{len(chunks)}, read={read_start.date()}..{chunk_end.date()}, write={chunk_start.date()}..{chunk_end.date()}",
        )
        data = pd.read_parquet(
            feature_path,
            columns=columns,
            filters=[("date", ">=", read_start), ("date", "<=", chunk_end), *filters_base],
        )
        if data.empty:
            _emit_progress(
                progress_callback,
                percent=chunk_base + chunk_span,
                step="chunk_empty",
                message="factor_cabinet feature cache chunk has no rows",
                detail=f"chunk={index}/{len(chunks)}",
            )
            continue
        _emit_progress(
            progress_callback,
            percent=chunk_base + chunk_span * 0.18,
            step="chunk_compute",
            message="computing factor_cabinet candidate factors",
            detail=f"chunk={index}/{len(chunks)}, rows={len(data)}, raw_columns={len(raw_columns)}",
        )
        # PIT fundamentals, RSI timing fields, and passthrough score columns
        # have dedicated materializers below (or already exist in the source).
        # Feeding them to the broad candidate generator disables its focused
        # path and needlessly computes the entire candidate library.
        candidate_columns = (
            set(raw_columns)
            - set(FACTOR_CABINET_PASSTHROUGH_COLUMNS)
            - set(rsi_timing_raw_columns())
            - set(pit_factor_raw_columns())
        )
        if candidate_columns:
            data = append_candidate_factors(
                data,
                close_col="close",
                include_columns=candidate_columns,
                include_ultra_grid=True,
            )
        if set(raw_columns) & set(rsi_timing_raw_columns()):
            data = append_rsi_timing_factors(data, close_col="close")
        if set(raw_columns) & set(pit_factor_raw_columns()):
            data = attach_pit_level2_factors(data, requested_columns=raw_columns)
        _emit_progress(
            progress_callback,
            percent=chunk_base + chunk_span * 0.72,
            step="chunk_filter",
            message="filtering computed factor_cabinet cache rows",
            detail=f"chunk={index}/{len(chunks)}, rows={len(data)}",
        )
        missing = sorted(set(raw_columns) - set(data.columns))
        if missing:
            raise ValueError(f"factor_cabinet feature cache chunk generation failed for columns: {missing}")
        data["date"] = pd.to_datetime(data["date"], errors="coerce")
        mask = data["date"].between(chunk_start, chunk_end, inclusive="both")
        cache = data.loc[mask, list(FACTOR_CACHE_INDEX_COLUMNS) + list(raw_columns)].copy()
        if cache.empty:
            del data, cache
            gc.collect()
            _emit_progress(
                progress_callback,
                percent=chunk_base + chunk_span,
                step="chunk_empty_write",
                message="factor_cabinet feature cache chunk produced no writable rows",
                detail=f"chunk={index}/{len(chunks)}",
            )
            continue
        cache = cache.dropna(subset=["date", "symbol"]).sort_values(["date", "symbol"])
        for column in raw_columns:
            cache[column] = pd.to_numeric(cache[column], errors="coerce").astype("float32")
        _emit_progress(
            progress_callback,
            percent=chunk_base + chunk_span * 0.86,
            step="chunk_write",
            message="writing factor_cabinet feature cache chunk",
            detail=f"chunk={index}/{len(chunks)}, rows={len(cache)}",
        )
        table = pa.Table.from_pandas(cache, preserve_index=False)
        part_path = dataset_path / f"part-{index:04d}.parquet"
        pq.write_table(table, part_path)
        row_count += int(len(cache))
        symbol_values.update(cache["symbol"].astype(str).unique().tolist())
        chunk_min = cache["date"].min()
        chunk_max = cache["date"].max()
        written_date_min = chunk_min if written_date_min is None else min(written_date_min, chunk_min)
        written_date_max = chunk_max if written_date_max is None else max(written_date_max, chunk_max)
        del data, cache, table
        gc.collect()
        _emit_progress(
            progress_callback,
            percent=chunk_base + chunk_span,
            step="chunk_complete",
            message="factor_cabinet feature cache chunk complete",
            detail=f"chunk={index}/{len(chunks)}, total_rows={row_count}",
        )

    if row_count <= 0 or written_date_min is None or written_date_max is None:
        raise ValueError(f"No feature rows available for factor_cabinet feature cache: {requested_start.date()} to {requested_end.date()}")
    return dataset_path, manifest_path, {
        "row_count": row_count,
        "symbol_count": len(symbol_values),
        "date_min": pd.Timestamp(written_date_min).strftime("%Y-%m-%d"),
        "date_max": pd.Timestamp(written_date_max).strftime("%Y-%m-%d"),
        "chunk_count": len(chunks),
        "storage_layout": "partitioned_parquet_directory",
    }


def _iter_fixed_day_chunks(start_date, end_date, *, days: int = 92):
    cursor = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    while cursor <= end:
        chunk_end = min(cursor + pd.Timedelta(days=max(int(days), 1) - 1), end)
        yield cursor, chunk_end
        cursor = chunk_end + pd.Timedelta(days=1)


def find_factor_cabinet_feature_cache(
    spec: FactorSourceSpec,
    start_date,
    end_date,
    *,
    feature_path: Path = FEATURE_DAILY_PARQUET,
    root: str | Path = FACTOR_CABINET_FEATURE_CACHE_ROOT,
) -> tuple[Path, dict] | tuple[None, dict]:
    if not spec.uses_factor_cabinet:
        return None, {"status": "legacy_source_has_no_factor_cabinet_cache"}
    raw_columns = _factor_cabinet_raw_columns(spec)
    cache_dir = Path(root) / str(spec.factor_cabinet_run_id)
    if not cache_dir.exists():
        return None, {"status": "missing_factor_cabinet_feature_cache_dir", "cache_dir": str(cache_dir)}
    matches: list[tuple[Path, dict]] = []
    for manifest_path in cache_dir.glob("factor_cabinet_features_*.manifest.json"):
        manifest = _read_manifest(manifest_path)
        parquet_path = _resolve_cache_artifact_path(
            manifest_path,
            manifest.get("parquet_path", ""),
        )
        if not parquet_path.exists():
            parquet_path = manifest_path.with_suffix("").with_suffix(".parquet")
        if parquet_path.exists() and _manifest_matches(
            manifest,
            spec=spec,
            start_date=start_date,
            end_date=end_date,
            raw_columns=raw_columns,
            feature_path=feature_path,
        ) and _parquet_has_columns(parquet_path, set(FACTOR_CACHE_INDEX_COLUMNS) | set(raw_columns)):
            if not str(manifest.get("cabinet_manifest_hash") or "").strip():
                _migrate_legacy_manifest_hash(manifest_path, manifest, spec)
            matches.append((parquet_path, manifest))
    if not matches:
        return None, {
            "status": "missing_or_stale_factor_cabinet_feature_cache",
            "cache_dir": str(cache_dir),
            "factor_cabinet_run_id": spec.factor_cabinet_run_id,
            "required_date_min": pd.Timestamp(start_date).strftime("%Y-%m-%d"),
            "required_date_max": pd.Timestamp(end_date).strftime("%Y-%m-%d"),
            "required_raw_columns": list(raw_columns),
        }
    return max(matches, key=lambda item: item[1].get("created_at", "")), {"status": "factor_cabinet_feature_cache_found"}


def load_factor_cabinet_feature_cache(
    spec: FactorSourceSpec,
    start_date,
    end_date,
    *,
    feature_path: Path = FEATURE_DAILY_PARQUET,
    requested_columns: tuple[str, ...] | list[str] | None = None,
) -> pd.DataFrame:
    found, status = find_factor_cabinet_feature_cache(
        spec,
        start_date,
        end_date,
        feature_path=feature_path,
    )
    raw_columns = _factor_cabinet_raw_columns(spec)
    if requested_columns is not None:
        unknown = sorted(set(requested_columns) - set(raw_columns))
        if unknown:
            raise ValueError(f"requested columns are not part of factor_cabinet: {unknown}")
        raw_columns = tuple(dict.fromkeys(str(column) for column in requested_columns))
    artifacts = [found] if found is not None else _find_factor_cabinet_feature_cache_cover(
        spec,
        start_date,
        end_date,
        feature_path=feature_path,
    )
    if not artifacts:
        raise FileNotFoundError(
            "factor_cabinet feature cache is required but missing or stale. "
            "Build it first with the Web task 'factor_cabinet 特征缓存/物化' "
            f"or CLI --factor-cabinet-feature-cache. Detail: {status}"
        )
    frames = [
        pd.read_parquet(
            parquet_path,
            columns=list(FACTOR_CACHE_INDEX_COLUMNS) + list(raw_columns),
            filters=[("date", ">=", pd.Timestamp(start_date)), ("date", "<=", pd.Timestamp(end_date))],
        )
        for parquet_path, _manifest in artifacts
    ]
    cache = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
    cache["date"] = pd.to_datetime(cache["date"], errors="coerce")
    if len(frames) > 1:
        cache = cache.sort_values(list(FACTOR_CACHE_INDEX_COLUMNS)).drop_duplicates(
            list(FACTOR_CACHE_INDEX_COLUMNS),
            keep="last",
        )
    return cache


def _find_factor_cabinet_feature_cache_cover(
    spec: FactorSourceSpec,
    start_date,
    end_date,
    *,
    feature_path: Path = FEATURE_DAILY_PARQUET,
    root: str | Path = FACTOR_CABINET_FEATURE_CACHE_ROOT,
) -> list[tuple[Path, dict]]:
    """Find an identity-consistent set of adjacent cache artifacts covering a window."""
    requested_start = pd.Timestamp(start_date).normalize()
    requested_end = pd.Timestamp(end_date).normalize()
    raw_columns = _factor_cabinet_raw_columns(spec)
    cache_dir = Path(root) / str(spec.factor_cabinet_run_id)
    candidates: list[tuple[pd.Timestamp, pd.Timestamp, Path, dict]] = []
    if not cache_dir.exists():
        return []
    for manifest_path in cache_dir.glob("factor_cabinet_features_*.manifest.json"):
        manifest = _read_manifest(manifest_path)
        parquet_path = _resolve_cache_artifact_path(
            manifest_path,
            manifest.get("parquet_path", ""),
        )
        if not parquet_path.exists():
            parquet_path = manifest_path.with_suffix("").with_suffix(".parquet")
        if not parquet_path.exists() or not _manifest_identity_matches(
            manifest,
            spec=spec,
            raw_columns=raw_columns,
            feature_path=feature_path,
        ):
            continue
        if not _parquet_has_columns(
            parquet_path,
            set(FACTOR_CACHE_INDEX_COLUMNS) | set(raw_columns),
        ):
            continue
        if not str(manifest.get("cabinet_manifest_hash") or "").strip():
            _migrate_legacy_manifest_hash(manifest_path, manifest, spec)
        usable_start, usable_end = _manifest_usable_window(manifest)
        if usable_end >= requested_start and usable_start <= requested_end:
            candidates.append((usable_start, usable_end, parquet_path, manifest))

    selected: list[tuple[Path, dict]] = []
    cursor = requested_start
    while cursor <= requested_end:
        eligible = [item for item in candidates if item[0] <= cursor <= item[1]]
        if not eligible:
            return []
        chosen = max(eligible, key=lambda item: (item[1], item[3].get("created_at", "")))
        selected.append((chosen[2], chosen[3]))
        cursor = chosen[1] + pd.Timedelta(days=1)
    return selected


def attach_factor_cabinet_feature_cache(
    data: pd.DataFrame,
    *,
    spec: FactorSourceSpec,
    start_date,
    end_date,
    feature_path: Path = FEATURE_DAILY_PARQUET,
) -> pd.DataFrame:
    if spec.factor_source == FACTOR_SOURCE_LEGACY:
        return data
    raw_columns = _factor_cabinet_raw_columns(spec)
    if not raw_columns:
        return data
    columns_to_attach = tuple(column for column in raw_columns if column not in data.columns)
    if not columns_to_attach:
        return data
    cache = load_factor_cabinet_feature_cache(
        spec,
        start_date,
        end_date,
        feature_path=feature_path,
        requested_columns=columns_to_attach,
    )
    unexpected_overlap = sorted(
        (set(data.columns) & set(cache.columns)) - set(FACTOR_CACHE_INDEX_COLUMNS)
    )
    if unexpected_overlap:
        raise ValueError(
            "factor_cabinet feature cache has unexpected overlapping columns: "
            f"{unexpected_overlap}"
        )
    merged = data.merge(cache, on=list(FACTOR_CACHE_INDEX_COLUMNS), how="left", validate="one_to_one")
    missing = sorted(column for column in raw_columns if column not in merged.columns)
    if missing:
        raise ValueError(f"factor_cabinet feature cache merge failed for columns: {missing}")
    return merged


def _read_manifest(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def validate_factor_cabinet_feature_cache_artifacts(
    parquet_path: str | Path,
    manifest_path: str | Path,
) -> tuple[Path, Path]:
    """Validate either a single parquet file or a partitioned parquet dataset."""
    manifest_path = Path(manifest_path).resolve()
    if not manifest_path.is_file():
        raise FileNotFoundError(f"factor_cabinet cache manifest does not exist: {manifest_path}")
    manifest = _read_manifest(manifest_path)
    if manifest.get("artifact_type") != "factor_cabinet_feature_cache":
        raise ValueError(f"invalid factor_cabinet cache manifest type: {manifest_path}")
    if int(manifest.get("row_count") or 0) <= 0:
        raise ValueError(f"factor_cabinet cache manifest has no rows: {manifest_path}")

    resolved_parquet = _resolve_cache_artifact_path(manifest_path, parquet_path)
    if not resolved_parquet.exists():
        raise FileNotFoundError(f"factor_cabinet cache parquet artifact does not exist: {resolved_parquet}")
    if resolved_parquet.is_dir():
        parts = sorted(resolved_parquet.glob("*.parquet"))
        if not parts:
            raise FileNotFoundError(f"factor_cabinet cache dataset has no parquet parts: {resolved_parquet}")
        if manifest.get("storage_layout") != "partitioned_parquet_directory":
            raise ValueError(
                "factor_cabinet cache directory is not declared as partitioned parquet: "
                f"{resolved_parquet}"
            )
    elif not resolved_parquet.is_file():
        raise FileNotFoundError(f"factor_cabinet cache artifact is not readable: {resolved_parquet}")

    required_columns = set(FACTOR_CACHE_INDEX_COLUMNS) | set(manifest.get("raw_columns", []))
    if not required_columns or not _parquet_has_columns(resolved_parquet, required_columns):
        raise ValueError(f"factor_cabinet cache schema is incomplete: {resolved_parquet}")

    declared_parquet = _resolve_cache_artifact_path(manifest_path, manifest.get("parquet_path", ""))
    if declared_parquet.exists() and declared_parquet.resolve() != resolved_parquet.resolve():
        raise ValueError(
            "factor_cabinet cache path does not match its manifest: "
            f"artifact={resolved_parquet}, declared={declared_parquet}"
        )
    return resolved_parquet.resolve(), manifest_path


def _resolve_cache_artifact_path(manifest_path: Path, value: str | Path) -> Path:
    path = Path(value) if str(value or "").strip() else Path("__missing_cache_artifact__")
    if path.is_absolute():
        return path
    candidates = (
        PROJECT_ROOT / path,
        Path(manifest_path).resolve().parent / path.name,
        Path.cwd() / path,
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _write_manifest_atomic(path: Path, payload: dict) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temp_path.replace(path)


def _factor_cabinet_raw_columns(spec: FactorSourceSpec) -> tuple[str, ...]:
    raw_columns = [
        str(column)
        for column in (spec.model_feature_map or {}).values()
        if is_factor_cabinet_runtime_column(column)
    ]
    if not raw_columns and spec.uses_factor_cabinet:
        raise ValueError("factor_cabinet source has no valid runtime factor columns")
    return tuple(dict.fromkeys(raw_columns))


def _manifest_matches(
    manifest: dict,
    *,
    spec: FactorSourceSpec,
    start_date,
    end_date,
    raw_columns: tuple[str, ...],
    feature_path: Path,
) -> bool:
    if not _manifest_identity_matches(
        manifest,
        spec=spec,
        raw_columns=raw_columns,
        feature_path=feature_path,
    ):
        return False
    usable_date_min, usable_date_max = _manifest_usable_window(manifest)
    return usable_date_min <= pd.Timestamp(start_date) and usable_date_max >= pd.Timestamp(end_date)


def _manifest_identity_matches(
    manifest: dict,
    *,
    spec: FactorSourceSpec,
    raw_columns: tuple[str, ...],
    feature_path: Path,
) -> bool:
    if manifest.get("artifact_type") != "factor_cabinet_feature_cache":
        return False
    if manifest.get("factor_cabinet_run_id") != spec.factor_cabinet_run_id:
        return False
    cached_hash = str(manifest.get("cabinet_manifest_hash") or "").strip()
    if cached_hash and cached_hash != spec.cabinet_manifest_hash:
        return False
    if set(manifest.get("raw_columns", [])) < set(raw_columns):
        return False
    if not _same_feature_fingerprint(manifest.get("feature_input", {}), file_fingerprint(feature_path)):
        return False
    return True


def _manifest_usable_window(manifest: dict) -> tuple[pd.Timestamp, pd.Timestamp]:
    usable_date_min = pd.Timestamp(
        manifest.get("requested_date_min") or manifest.get("usable_date_min", manifest.get("date_min"))
    )
    usable_date_max = pd.Timestamp(manifest.get("requested_date_max") or manifest.get("date_max"))
    return usable_date_min.normalize(), usable_date_max.normalize()


def _migrate_legacy_manifest_hash(manifest_path: Path, manifest: dict, spec: FactorSourceSpec) -> None:
    """Upgrade a pre-hash cache only after all normal cache checks have passed."""
    upgraded = dict(manifest)
    upgraded["cabinet_manifest_hash"] = spec.cabinet_manifest_hash
    upgraded["cache_contract_version"] = "factor_cabinet_runtime_context_v1"
    temp_path = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(upgraded, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temp_path.replace(manifest_path)
    manifest.update(upgraded)


def _same_feature_fingerprint(left: dict, right: dict) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    return (
        bool(left.get("exists")) == bool(right.get("exists"))
        and int(left.get("size") or -1) == int(right.get("size") or -2)
        and int(left.get("mtime_ns") or -1) == int(right.get("mtime_ns") or -2)
    )


def _parquet_has_columns(path: Path, required_columns: set[str]) -> bool:
    try:
        if Path(path).is_dir():
            import pyarrow.dataset as ds

            schema_columns = set(ds.dataset(path, format="parquet").schema.names)
        else:
            import pyarrow.parquet as pq

            schema_columns = set(pq.read_schema(path).names)
    except Exception:
        return False
    return set(required_columns).issubset(schema_columns)


def _emit_progress(progress_callback, **payload) -> None:
    step = str(payload.get("step", ""))
    message = str(payload.get("message", ""))
    detail = str(payload.get("detail", ""))
    if step or message:
        suffix = f" | {detail}" if detail else ""
        print(f"[factor_cabinet_feature_cache] {step}: {message}{suffix}", flush=True)
    if progress_callback is None:
        return
    try:
        progress_callback(payload)
    except Exception:
        pass
