"""Productized cache for pre-screen candidate governance factors."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import (
    FEATURE_DAILY_PARQUET,
    GOVERNANCE_ALPHA_MODEL_FEATURES,
    GOVERNANCE_PRE_SCREEN_FACTOR_CACHE_BUNDLE,
    GOVERNANCE_PRE_SCREEN_FACTOR_CACHE_DIR,
    GOVERNANCE_PRE_SCREEN_FACTOR_CACHE_LOOKBACK_DAYS,
    GOVERNANCE_PRE_SCREEN_FACTOR_CACHE_VERSION,
    GOVERNANCE_PRE_SCREEN_FACTOR_JUDGE_RUN_ID,
    GOVERNANCE_PRE_SCREEN_FACTOR_ROLE_WEIGHTS,
    GOVERNANCE_PRE_SCREEN_SELECTED_ALPHA_MODELS,
)
from functions.factors.factor_candidate_pool import append_candidate_factors
from functions.pipeline_cache import file_fingerprint


FACTOR_CACHE_INDEX_COLUMNS = ("date", "symbol")


def pre_screen_candidate_model_names(alpha_models: tuple[str, ...] | None = None) -> tuple[str, ...]:
    models = tuple(alpha_models or GOVERNANCE_PRE_SCREEN_SELECTED_ALPHA_MODELS)
    return tuple(
        model
        for model in models
        if model in GOVERNANCE_ALPHA_MODEL_FEATURES
        and str(GOVERNANCE_ALPHA_MODEL_FEATURES[model]).startswith("cand_")
    )


def pre_screen_candidate_raw_columns(alpha_models: tuple[str, ...] | None = None) -> tuple[str, ...]:
    return tuple(GOVERNANCE_ALPHA_MODEL_FEATURES[model] for model in pre_screen_candidate_model_names(alpha_models))


def candidate_factor_cache_dir(
    *,
    judge_run_id: str = GOVERNANCE_PRE_SCREEN_FACTOR_JUDGE_RUN_ID,
    bundle_name: str = GOVERNANCE_PRE_SCREEN_FACTOR_CACHE_BUNDLE,
) -> Path:
    return Path(GOVERNANCE_PRE_SCREEN_FACTOR_CACHE_DIR) / str(judge_run_id) / str(bundle_name)


def candidate_factor_cache_paths(
    start_date,
    end_date,
    *,
    judge_run_id: str = GOVERNANCE_PRE_SCREEN_FACTOR_JUDGE_RUN_ID,
    bundle_name: str = GOVERNANCE_PRE_SCREEN_FACTOR_CACHE_BUNDLE,
) -> tuple[Path, Path]:
    start = pd.Timestamp(start_date).strftime("%Y%m%d")
    end = pd.Timestamp(end_date).strftime("%Y%m%d")
    base = candidate_factor_cache_dir(judge_run_id=judge_run_id, bundle_name=bundle_name)
    stem = f"candidate_factors_{start}_{end}"
    return base / f"{stem}.parquet", base / f"{stem}.manifest.json"


def candidate_factor_source_columns() -> list[str]:
    return [
        "date",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "amount",
        "volume",
        "ret_1",
        "ret_5",
        "ret_10",
        "ret_20",
        "ret_60",
        "ma_5",
        "ma_10",
        "ma_20",
        "ma_60",
        "ma_120",
        "volatility_20",
        "volatility_60",
        "float_cap",
        "total_cap",
        "stabilized_float_cap",
        "stabilized_total_cap",
        "upper_shadow",
        "lower_shadow",
        "body_ratio",
        "sector_parent",
        "index_pool_codes",
        "instrument_type",
        "is_trading",
        "abnormal_jump",
        "close_nominal",
        "open_nominal",
        "high_nominal",
        "low_nominal",
        "amount_ma20",
    ]


def candidate_factor_cache_manifest(
    *,
    parquet_path: Path,
    feature_path: Path,
    start_date,
    end_date,
    alpha_models: tuple[str, ...],
    raw_columns: tuple[str, ...],
    row_count: int,
    symbol_count: int,
    symbol_scope: str,
) -> dict:
    return {
        "artifact_type": "pre_screen_candidate_factor_cache",
        "cache_version": GOVERNANCE_PRE_SCREEN_FACTOR_CACHE_VERSION,
        "judge_run_id": GOVERNANCE_PRE_SCREEN_FACTOR_JUDGE_RUN_ID,
        "bundle_name": GOVERNANCE_PRE_SCREEN_FACTOR_CACHE_BUNDLE,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "date_min": pd.Timestamp(start_date).strftime("%Y-%m-%d"),
        "date_max": pd.Timestamp(end_date).strftime("%Y-%m-%d"),
        "usable_date_min": (
            pd.Timestamp(start_date) + pd.Timedelta(days=int(GOVERNANCE_PRE_SCREEN_FACTOR_CACHE_LOOKBACK_DAYS))
        ).strftime("%Y-%m-%d"),
        "lookback_days": int(GOVERNANCE_PRE_SCREEN_FACTOR_CACHE_LOOKBACK_DAYS),
        "alpha_models": list(alpha_models),
        "raw_columns": list(raw_columns),
        "role_weights": GOVERNANCE_PRE_SCREEN_FACTOR_ROLE_WEIGHTS,
        "symbol_scope": str(symbol_scope),
        "row_count": int(row_count),
        "symbol_count": int(symbol_count),
        "parquet_path": str(parquet_path),
        "feature_input": file_fingerprint(feature_path),
    }


def build_pre_screen_candidate_factor_cache(
    start_date,
    end_date,
    *,
    alpha_models: tuple[str, ...] | None = None,
    feature_path: Path = FEATURE_DAILY_PARQUET,
    output_path: Path | None = None,
    manifest_path: Path | None = None,
    allowed_instrument_types: tuple[str, ...] = ("stock", "etf_fund"),
    symbol_scope: str = "all",
) -> tuple[Path, Path]:
    """Build a fixed parquet cache for selected pre-screen candidate factors."""
    models = pre_screen_candidate_model_names(alpha_models)
    raw_columns = pre_screen_candidate_raw_columns(models)
    if not raw_columns:
        raise ValueError("No pre-screen candidate raw columns requested.")

    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    output_path, manifest_path = (
        (Path(output_path), Path(manifest_path))
        if output_path is not None and manifest_path is not None
        else candidate_factor_cache_paths(start_ts, end_ts)
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    import pyarrow.parquet as pq

    available_columns = set(pq.read_schema(feature_path).names)
    columns = [column for column in candidate_factor_source_columns() if column in available_columns]
    filters = [("date", ">=", start_ts), ("date", "<=", end_ts)]
    if allowed_instrument_types and "instrument_type" in available_columns:
        filters.append(("instrument_type", "in", list(tuple(dict.fromkeys(allowed_instrument_types)))))

    data = pd.read_parquet(feature_path, columns=columns, filters=filters)
    if data.empty:
        raise ValueError(f"No feature rows available for candidate factor cache: {start_ts.date()} to {end_ts.date()}")
    data = append_candidate_factors(
        data,
        close_col="close",
        include_columns=set(raw_columns),
        include_ultra_grid=True,
    )
    missing = sorted(set(raw_columns) - set(data.columns))
    if missing:
        raise ValueError(f"Candidate factor cache generation failed for columns: {missing}")

    cache = data.loc[:, list(FACTOR_CACHE_INDEX_COLUMNS) + list(raw_columns)].copy()
    cache["date"] = pd.to_datetime(cache["date"], errors="coerce")
    cache = cache.dropna(subset=["date", "symbol"]).sort_values(["date", "symbol"])
    for column in raw_columns:
        cache[column] = pd.to_numeric(cache[column], errors="coerce").astype("float32")
    cache.to_parquet(output_path, index=False)

    manifest = candidate_factor_cache_manifest(
        parquet_path=output_path,
        feature_path=Path(feature_path),
        start_date=cache["date"].min(),
        end_date=cache["date"].max(),
        alpha_models=models,
        raw_columns=raw_columns,
        row_count=len(cache),
        symbol_count=cache["symbol"].astype(str).nunique(),
        symbol_scope=symbol_scope,
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return output_path, manifest_path


def _read_manifest(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _manifest_matches(
    manifest: dict,
    *,
    start_date,
    end_date,
    raw_columns: tuple[str, ...],
    feature_path: Path,
) -> bool:
    if manifest.get("artifact_type") != "pre_screen_candidate_factor_cache":
        return False
    if manifest.get("cache_version") != GOVERNANCE_PRE_SCREEN_FACTOR_CACHE_VERSION:
        return False
    if manifest.get("judge_run_id") != GOVERNANCE_PRE_SCREEN_FACTOR_JUDGE_RUN_ID:
        return False
    if manifest.get("symbol_scope") != "all":
        return False
    if set(manifest.get("raw_columns", [])) < set(raw_columns):
        return False
    manifest_feature = manifest.get("feature_input", {})
    current_feature = file_fingerprint(feature_path)
    if manifest_feature != current_feature:
        return False
    usable_date_min = pd.Timestamp(manifest.get("usable_date_min", manifest.get("date_min")))
    date_max = pd.Timestamp(manifest.get("date_max"))
    return usable_date_min <= pd.Timestamp(start_date) and date_max >= pd.Timestamp(end_date)


def find_pre_screen_candidate_factor_cache(
    start_date,
    end_date,
    *,
    alpha_models: tuple[str, ...] | None = None,
    feature_path: Path = FEATURE_DAILY_PARQUET,
) -> tuple[Path, dict] | tuple[None, dict]:
    raw_columns = pre_screen_candidate_raw_columns(alpha_models)
    cache_dir = candidate_factor_cache_dir()
    if not cache_dir.exists():
        return None, {"status": "missing_candidate_factor_cache", "cache_dir": str(cache_dir)}
    matches: list[tuple[Path, dict]] = []
    for manifest_path in cache_dir.glob("candidate_factors_*.manifest.json"):
        manifest = _read_manifest(manifest_path)
        parquet_path = Path(manifest.get("parquet_path", ""))
        if not parquet_path.exists():
            parquet_path = manifest_path.with_suffix("").with_suffix(".parquet")
        if parquet_path.exists() and _manifest_matches(
            manifest,
            start_date=start_date,
            end_date=end_date,
            raw_columns=raw_columns,
            feature_path=Path(feature_path),
        ) and _parquet_has_columns(parquet_path, set(FACTOR_CACHE_INDEX_COLUMNS) | set(raw_columns)):
            matches.append((parquet_path, manifest))
    if not matches:
        return None, {
            "status": "missing_or_stale_candidate_factor_cache",
            "cache_dir": str(cache_dir),
            "required_date_min": pd.Timestamp(start_date).strftime("%Y-%m-%d"),
            "required_date_max": pd.Timestamp(end_date).strftime("%Y-%m-%d"),
            "required_raw_columns": list(raw_columns),
        }
    return max(matches, key=lambda item: item[1].get("created_at", "")), {"status": "candidate_factor_cache_found"}


def _parquet_has_columns(path: Path, required_columns: set[str]) -> bool:
    try:
        import pyarrow.parquet as pq

        schema_columns = set(pq.read_schema(path).names)
    except Exception:
        return False
    return set(required_columns).issubset(schema_columns)


def load_pre_screen_candidate_factor_cache(
    start_date,
    end_date,
    *,
    alpha_models: tuple[str, ...] | None = None,
    feature_path: Path = FEATURE_DAILY_PARQUET,
) -> pd.DataFrame:
    found, status = find_pre_screen_candidate_factor_cache(
        start_date,
        end_date,
        alpha_models=alpha_models,
        feature_path=feature_path,
    )
    if found is None:
        build_start = pd.Timestamp(start_date) - pd.Timedelta(days=int(GOVERNANCE_PRE_SCREEN_FACTOR_CACHE_LOOKBACK_DAYS))
        parquet_path, manifest_path = build_pre_screen_candidate_factor_cache(
            build_start,
            end_date,
            alpha_models=alpha_models,
            feature_path=feature_path,
        )
        manifest = _read_manifest(manifest_path)
    else:
        parquet_path, manifest = found
    raw_columns = pre_screen_candidate_raw_columns(alpha_models)
    try:
        cache = pd.read_parquet(
            parquet_path,
            columns=list(FACTOR_CACHE_INDEX_COLUMNS) + list(raw_columns),
            filters=[("date", ">=", pd.Timestamp(start_date)), ("date", "<=", pd.Timestamp(end_date))],
        )
    except Exception:
        build_start = pd.Timestamp(start_date) - pd.Timedelta(days=int(GOVERNANCE_PRE_SCREEN_FACTOR_CACHE_LOOKBACK_DAYS))
        parquet_path, manifest_path = build_pre_screen_candidate_factor_cache(
            build_start,
            end_date,
            alpha_models=alpha_models,
            feature_path=feature_path,
        )
        manifest = _read_manifest(manifest_path)
        cache = pd.read_parquet(
            parquet_path,
            columns=list(FACTOR_CACHE_INDEX_COLUMNS) + list(raw_columns),
            filters=[("date", ">=", pd.Timestamp(start_date)), ("date", "<=", pd.Timestamp(end_date))],
        )
    cache["date"] = pd.to_datetime(cache["date"], errors="coerce")
    return cache


def attach_pre_screen_candidate_factor_cache(
    data: pd.DataFrame,
    *,
    start_date,
    end_date,
    alpha_models: tuple[str, ...],
    feature_path: Path = FEATURE_DAILY_PARQUET,
) -> pd.DataFrame:
    raw_columns = pre_screen_candidate_raw_columns(alpha_models)
    if not raw_columns:
        return data
    cache = load_pre_screen_candidate_factor_cache(
        start_date,
        end_date,
        alpha_models=alpha_models,
        feature_path=feature_path,
    )
    merged = data.merge(cache, on=list(FACTOR_CACHE_INDEX_COLUMNS), how="left", validate="one_to_one")
    missing = sorted(column for column in raw_columns if column not in merged.columns)
    if missing:
        raise ValueError(f"Candidate factor cache merge failed for columns: {missing}")
    return merged
