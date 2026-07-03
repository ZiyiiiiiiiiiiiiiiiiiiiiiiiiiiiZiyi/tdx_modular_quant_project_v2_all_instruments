"""Fast factor judge route.

This route deliberately avoids the governance state machine. It reads the
feature parquet, applies the same universe/date filters, runs factor IC/layer
diagnostics, and writes compact reports for pre-screening.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    COMMISSION_RATE,
    FEATURE_DAILY_PARQUET,
    GOVERNANCE_OUTPUT_DIR,
    SLIPPAGE_RATE,
    STAMP_DUTY_RATE,
    TRANSFER_FEE_RATE,
)
from functions.decision_council.factor_registry import build_factor_registry
from functions.decision_council.factor_validation import build_factor_research_reports
from functions.decision_council.factor_pool_contract import build_role_coverage_report, load_factor_pool_contract
from functions.factors.factor_candidate_pool import append_candidate_factors
from functions.investable_universe import UniverseFilterConfig, filter_investable_universe, load_index_constituents
from functions.universe_registry import get_universe_spec


FAST_FACTOR_JUDGE_DIR = GOVERNANCE_OUTPUT_DIR / "fast_factor_judge"
FAST_FACTOR_BATCH_SIZE = 200
FAST_FACTOR_QUICK_HORIZONS = (10,)
FAST_FACTOR_FULL_HORIZONS = (5, 10, 20)


def run_fast_factor_judge(
    *,
    universe_name: str = "hs300_csi500_a500_strict",
    start_date: str | None = None,
    end_date: str | None = None,
    max_days: int | None = 180,
    feature_path=FEATURE_DAILY_PARQUET,
    output_dir=FAST_FACTOR_JUDGE_DIR,
    progress_callback=None,
    max_factor_count: int | None = None,
    large_pool_horizons=None,
) -> dict[str, Path]:
    """Run fast read-only factor diagnostics."""
    _emit_progress(progress_callback, percent=1.0, step="prepare", message="checking feature parquet")
    feature_path = Path(feature_path)
    if not feature_path.exists():
        raise FileNotFoundError(f"Feature parquet not found: {feature_path}")
    run_created_at = datetime.now()
    run_id = run_created_at.strftime("run%Y%m%d_%H%M%S_%f")
    output = Path(output_dir) / str(universe_name) / run_id
    suffix = 1
    while output.exists():
        suffix += 1
        output = Path(output_dir) / str(universe_name) / f"{run_id}_{suffix}"
    output.mkdir(parents=True, exist_ok=True)

    _emit_progress(progress_callback, percent=5.0, step="load_features", message="reading feature window")
    feature_data = _load_feature_window(feature_path, start_date=start_date, end_date=end_date, max_days=max_days)
    _emit_progress(
        progress_callback,
        percent=18.0,
        step="filter_universe",
        message="applying investable universe",
        detail=f"rows_before_filter={len(feature_data)}",
    )
    feature_data = _apply_universe(feature_data, universe_name=universe_name)
    feature_data = _limit_recent_days(feature_data, max_days=max_days)
    registry = build_factor_registry()
    if max_factor_count is not None and int(max_factor_count) > 0:
        registry = dict(list(registry.items())[: int(max_factor_count)])
    effective_large_pool_horizons = tuple(large_pool_horizons or FAST_FACTOR_QUICK_HORIZONS)
    reports = _build_fast_factor_reports(
        feature_data,
        registry=registry,
        progress_callback=progress_callback,
        large_pool_horizons=effective_large_pool_horizons,
    )

    _emit_progress(progress_callback, percent=88.0, step="summary", message="building cost adjusted summary")
    validation = _attach_cost_adjusted_metrics(reports.get("governance_factor_validation_report", pd.DataFrame()))
    reports["fast_factor_validation_report"] = validation
    reports["governance_factor_validation_report"] = validation
    reports["fast_factor_summary"] = build_fast_factor_summary(validation)
    analysis_start_date = _date_min(feature_data)
    analysis_end_date = _date_max(feature_data)
    row_count = int(len(feature_data))
    symbol_count = int(feature_data["symbol"].nunique()) if "symbol" in feature_data.columns else 0
    run_created_at_text = run_created_at.strftime("%Y-%m-%d %H:%M:%S.%f")
    reports = _stamp_report_metadata(
        reports,
        run_id=output.name,
        run_created_at=run_created_at_text,
        universe_name=universe_name,
        analysis_start_date=analysis_start_date,
        analysis_end_date=analysis_end_date,
    )
    reports["fast_factor_judge_manifest"] = pd.DataFrame(
        [
            {
                "run_id": output.name,
                "run_created_at": run_created_at_text,
                "universe_name": universe_name,
                "analysis_start_date": analysis_start_date,
                "analysis_end_date": analysis_end_date,
                "max_days": max_days,
                "factor_count": int(len(registry)),
                "batch_size": int(FAST_FACTOR_BATCH_SIZE) if len(registry) > 1000 else None,
                "large_pool_horizons": "|".join(str(int(horizon)) for horizon in effective_large_pool_horizons),
                "cluster_skipped_for_large_pool": bool(len(registry) > 1000),
                "quantile_rows_emitted": bool(len(registry) <= 1000),
                "row_count": row_count,
                "symbol_count": symbol_count,
                "feature_path": str(feature_path),
                "round_trip_cost_rate": _round_trip_cost_rate(),
                "state_machine_used": False,
                "order_simulation_used": False,
                "purpose": "pre_screen_candidate_factor_judgement",
            }
        ]
    )

    saved: dict[str, Path] = {}
    _emit_progress(progress_callback, percent=94.0, step="save_reports", message="saving fast judge reports")
    for name, frame in reports.items():
        if frame is None:
            continue
        path = output / f"{name}.csv"
        frame.to_csv(path, index=False, encoding="utf-8-sig")
        saved[name] = path
    contract = load_factor_pool_contract(saved["fast_factor_summary"])
    role_coverage = build_role_coverage_report(contract)
    contract_path = output / "factor_pool_contract.csv"
    role_path = output / "factor_role_coverage.csv"
    contract.to_csv(contract_path, index=False, encoding="utf-8-sig")
    role_coverage.to_csv(role_path, index=False, encoding="utf-8-sig")
    saved["factor_pool_contract"] = contract_path
    saved["factor_role_coverage"] = role_path
    report_path = output / "fast_factor_judge_report.md"
    report_path.write_text(render_fast_factor_judge_markdown(reports), encoding="utf-8")
    saved["fast_factor_judge_report"] = report_path
    manifest_json = output / "fast_factor_judge_manifest.json"
    manifest_json.write_text(
        json.dumps({key: str(value) for key, value in saved.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    saved["fast_factor_judge_manifest_json"] = manifest_json
    _emit_progress(progress_callback, percent=100.0, step="complete", message="fast factor judge complete")
    return saved


def build_fast_factor_summary(validation: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "candidate_pool",
        "factor_name",
        "raw_column",
        "module",
        "best_horizon_days",
        "pass_count",
        "best_ic_ir",
        "best_rank_ic_mean",
        "best_top_bottom_spread",
        "best_cost_adjusted_top_bottom_spread",
        "avg_turnover_mean",
        "verdict",
        "reason",
    ]
    if validation is None or validation.empty:
        return pd.DataFrame(columns=columns)
    data = validation.copy()
    data["pass_flag"] = data.get("pass_flag", pd.Series(False, index=data.index)).fillna(False).astype(bool)
    for column in ["ic_ir", "rank_ic_mean", "top_bottom_spread", "cost_adjusted_top_bottom_spread", "turnover_mean"]:
        data[column] = pd.to_numeric(data.get(column), errors="coerce")
    rows = []
    for factor_name, group in data.groupby("factor_name", sort=True):
        ranked = group.sort_values(["pass_flag", "cost_adjusted_top_bottom_spread", "ic_ir"], ascending=[False, False, False])
        best = ranked.iloc[0]
        pass_count = int(group["pass_flag"].sum())
        horizon_count = int(pd.to_numeric(group.get("horizon_days"), errors="coerce").dropna().nunique())
        required_pass_count = 1 if horizon_count <= 1 else 2
        cost_spread = float(best["cost_adjusted_top_bottom_spread"]) if pd.notna(best["cost_adjusted_top_bottom_spread"]) else np.nan
        if pass_count >= required_pass_count and np.isfinite(cost_spread) and cost_spread > 0.0:
            verdict = "promote_candidate"
            reason = "pass_and_positive_after_cost" if required_pass_count == 1 else "multi_horizon_pass_and_positive_after_cost"
        elif pass_count >= 1:
            verdict = "watchlist"
            reason = "single_horizon_or_cost_sensitive_pass"
        else:
            verdict = "reject_or_rework"
            reason = str(best.get("fail_reasons", "failed_validation"))
        rows.append(
            {
                "candidate_pool": best.get("candidate_pool", "unknown"),
                "factor_name": factor_name,
                "raw_column": best.get("raw_column", ""),
                "module": best.get("module", "unknown"),
                "best_horizon_days": _safe_int(best.get("horizon_days"), default=0),
                "pass_count": pass_count,
                "best_ic_ir": best["ic_ir"],
                "best_rank_ic_mean": best["rank_ic_mean"],
                "best_top_bottom_spread": best["top_bottom_spread"],
                "best_cost_adjusted_top_bottom_spread": best["cost_adjusted_top_bottom_spread"],
                "avg_turnover_mean": float(group["turnover_mean"].mean()) if group["turnover_mean"].notna().any() else np.nan,
                "verdict": verdict,
                "reason": reason,
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["verdict", "best_cost_adjusted_top_bottom_spread", "best_ic_ir"],
        ascending=[True, False, False],
    )


def _build_fast_factor_reports(
    feature_data: pd.DataFrame,
    *,
    registry: dict[str, dict],
    progress_callback=None,
    large_pool_horizons=None,
) -> dict[str, pd.DataFrame]:
    if len(registry) <= 1000:
        needed_factor_columns = {meta.get("raw_column") for meta in registry.values() if meta.get("raw_column")}
        _emit_progress(
            progress_callback,
            percent=22.0,
            step="generate_candidate_pool",
            message="generating missing pre-screen candidate factors",
            detail=f"rows={len(feature_data)}",
        )
        working = append_candidate_factors(
            feature_data,
            close_col="close_nominal" if "close_nominal" in feature_data.columns else "close",
            include_columns=needed_factor_columns,
            include_ultra_grid=True,
        )
        _emit_progress(
            progress_callback,
            percent=25.0,
            step="factor_validation",
            message="validating factors",
            detail=f"rows={len(working)}",
        )
        return build_factor_research_reports(
            working,
            registry=registry,
            progress_callback=_factor_validation_progress(progress_callback),
            emit_quantile_rows=True,
            cluster_max_factors=300,
        )

    registry_items = list(registry.items())
    horizons = tuple(large_pool_horizons or FAST_FACTOR_QUICK_HORIZONS)
    batches = [
        dict(registry_items[index : index + FAST_FACTOR_BATCH_SIZE])
        for index in range(0, len(registry_items), FAST_FACTOR_BATCH_SIZE)
    ]
    validation_parts: list[pd.DataFrame] = []
    ic_parts: list[pd.DataFrame] = []
    cluster_report = pd.DataFrame()
    snapshot = pd.DataFrame(
        [
            {"factor_name": name, **meta}
            for name, meta in registry.items()
        ]
    )
    total_batches = max(len(batches), 1)
    for batch_index, batch_registry in enumerate(batches, start=1):
        batch_columns = {meta.get("raw_column") for meta in batch_registry.values() if meta.get("raw_column")}
        _emit_progress(
            progress_callback,
            percent=22.0 + (batch_index - 1) / total_batches * 63.0,
            step="generate_candidate_pool",
            message=f"generating factor batch {batch_index}/{total_batches}",
            detail=f"batch_factors={len(batch_registry)} rows={len(feature_data)}",
        )
        working = append_candidate_factors(
            feature_data,
            close_col="close_nominal" if "close_nominal" in feature_data.columns else "close",
            include_columns=batch_columns,
            include_ultra_grid=True,
        )
        batch_base = 25.0 + (batch_index - 1) / total_batches * 60.0
        batch_span = 60.0 / total_batches

        def _batch_progress(payload: dict, *, base=batch_base, span=batch_span, bidx=batch_index):
            current = int(payload.get("current") or 0)
            total = max(int(payload.get("total") or 1), 1)
            _emit_progress(
                progress_callback,
                percent=base + (current / total) * span,
                step="factor_validation",
                message=f"validating batch {bidx}/{total_batches} factor {current}/{total}",
                detail=str(payload.get("factor_name") or ""),
                current=(bidx - 1) * FAST_FACTOR_BATCH_SIZE + current,
                total=len(registry),
            )

        batch_reports = build_factor_research_reports(
            working,
            registry=batch_registry,
            horizons=horizons,
            progress_callback=_batch_progress,
            emit_quantile_rows=False,
            cluster_max_factors=0,
        )
        validation = batch_reports.get("governance_factor_validation_report", pd.DataFrame())
        ic = batch_reports.get("governance_factor_ic_timeseries", pd.DataFrame())
        if validation is not None and not validation.empty:
            validation_parts.append(validation)
        if ic is not None and not ic.empty:
            ic_parts.append(ic)
        del working
        _emit_progress(
            progress_callback,
            percent=25.0 + batch_index / total_batches * 60.0,
            step="batch_complete",
            message=f"completed batch {batch_index}/{total_batches}",
            detail=f"validated_factors={min(batch_index * FAST_FACTOR_BATCH_SIZE, len(registry))}/{len(registry)}",
            current=min(batch_index * FAST_FACTOR_BATCH_SIZE, len(registry)),
            total=len(registry),
        )
    validation_report = pd.concat(validation_parts, ignore_index=True, sort=False) if validation_parts else pd.DataFrame()
    ic_report = pd.concat(ic_parts, ignore_index=True, sort=False) if ic_parts else pd.DataFrame()
    empty_quantile = pd.DataFrame()
    return {
        "governance_factor_registry_snapshot": snapshot,
        "governance_factor_validation_report": validation_report,
        "governance_factor_ic_timeseries": ic_report,
        "governance_factor_layer_return_report": empty_quantile,
        "governance_factor_quantile_report": empty_quantile,
        "governance_factor_cluster_report": cluster_report,
    }


def render_fast_factor_judge_markdown(reports: dict[str, pd.DataFrame]) -> str:
    manifest = reports.get("fast_factor_judge_manifest", pd.DataFrame())
    summary = reports.get("fast_factor_summary", pd.DataFrame())
    validation = reports.get("fast_factor_validation_report", pd.DataFrame())
    cluster = reports.get("governance_factor_cluster_report", pd.DataFrame())
    lines = [
        "# Fast Factor Judge Report",
        "",
        "This report is read-only. It does not run the governance state machine, order simulation, or portfolio allocation.",
        "",
    ]
    if manifest is not None and not manifest.empty:
        lines.extend(["## Manifest", manifest.to_markdown(index=False), ""])
    if summary is not None and not summary.empty:
        counts = summary["verdict"].value_counts().to_dict()
        lines.extend(["## Verdict Counts"])
        for verdict, count in sorted(counts.items()):
            lines.append(f"- `{verdict}`: {count}")
        show_cols = [
            "candidate_pool",
            "factor_name",
            "module",
            "best_horizon_days",
            "pass_count",
            "best_ic_ir",
            "best_cost_adjusted_top_bottom_spread",
            "avg_turnover_mean",
            "verdict",
        ]
        lines.extend(["", "## Top Promote Candidates"])
        promoted = summary[summary["verdict"].eq("promote_candidate")].head(30)
        lines.append(promoted.loc[:, [col for col in show_cols if col in promoted.columns]].to_markdown(index=False) if not promoted.empty else "No promote candidates.")
        lines.extend(["", "## Top Watchlist Candidates"])
        watch = summary[summary["verdict"].eq("watchlist")].head(30)
        lines.append(watch.loc[:, [col for col in show_cols if col in watch.columns]].to_markdown(index=False) if not watch.empty else "No watchlist candidates.")
    if validation is not None and not validation.empty:
        lines.extend(["", "## Factor-Horizon Validation Sample"])
        cols = [
            "candidate_pool",
            "factor_name",
            "module",
            "horizon_days",
            "coverage_ratio",
            "rank_ic_mean",
            "ic_ir",
            "top_bottom_spread",
            "turnover_mean",
            "cost_adjusted_top_bottom_spread",
            "pass_flag",
            "fail_reasons",
        ]
        data = validation.copy()
        data["pass_flag"] = data.get("pass_flag", pd.Series(False, index=data.index)).fillna(False).astype(bool)
        data["cost_adjusted_top_bottom_spread"] = pd.to_numeric(data.get("cost_adjusted_top_bottom_spread"), errors="coerce")
        sample = data.sort_values(["pass_flag", "cost_adjusted_top_bottom_spread"], ascending=[False, False]).head(40)
        lines.append(sample.loc[:, [col for col in cols if col in sample.columns]].to_markdown(index=False))
    if cluster is not None and not cluster.empty:
        lines.extend(["", "## Redundancy Clusters"])
        cols = [col for col in ["cluster_id", "factor_name", "candidate_pool", "module", "cluster_size", "avg_abs_corr", "max_abs_corr", "representative_factor", "drop_or_downweight", "reason"] if col in cluster.columns]
        lines.append(cluster.loc[:, cols].head(60).to_markdown(index=False))
    return "\n".join(lines) + "\n"


def _load_feature_window(
    feature_path: Path,
    *,
    start_date: str | None,
    end_date: str | None,
    max_days: int | None,
) -> pd.DataFrame:
    import pyarrow.parquet as pq

    available = set(pq.read_schema(feature_path).names)
    registry_columns = [meta.get("raw_column") for meta in build_factor_registry().values()]
    desired = {
        "date",
        "symbol",
        "instrument_type",
        "open",
        "high",
        "low",
        "close",
        "open_nominal",
        "high_nominal",
        "low_nominal",
        "close_nominal",
        "amount",
        "volume",
        "sector_parent",
        "stabilized_float_cap",
        "stabilized_total_cap",
        "float_cap",
        "total_cap",
        "ret_1",
        "ret_5",
        "ret_10",
        "ret_20",
        "ret_60",
        "volatility_20",
        "volatility_60",
        "ma_5",
        "ma_10",
        "ma_20",
        "ma_60",
        "ma_120",
        "is_st",
        "is_delisting",
        "is_trading",
        "rough_limit_up",
        "rough_limit_down",
        "formal_price_eligible",
        "raw_ret",
        *[column for column in registry_columns if column],
    }
    columns = [column for column in desired if column in available]
    missing_required = sorted({"date", "symbol"} - set(columns))
    if missing_required:
        raise ValueError(f"Feature parquet missing required columns: {missing_required}")
    read_start = start_date
    if not read_start and max_days is not None and int(max_days) > 0:
        read_start = _recent_start_date(feature_path, max_days=int(max_days))
    filters = _parquet_date_filters(start_date=read_start, end_date=end_date)
    try:
        data = pd.read_parquet(feature_path, columns=columns, filters=filters) if filters else pd.read_parquet(feature_path, columns=columns)
    except Exception:
        data = pd.read_parquet(feature_path, columns=columns)
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    if start_date:
        data = data[data["date"] >= pd.Timestamp(start_date)]
    elif read_start:
        data = data[data["date"] >= pd.Timestamp(read_start)]
    if end_date:
        data = data[data["date"] <= pd.Timestamp(end_date)]
    return data


def _apply_universe(feature_data: pd.DataFrame, *, universe_name: str) -> pd.DataFrame:
    spec = get_universe_spec(universe_name)
    cfg = UniverseFilterConfig(
        min_history_days=int(spec.min_history_days),
        min_avg_amount_20=float(spec.min_avg_amount_20),
        max_amihud_20=float(spec.max_amihud_20),
        abnormal_return_threshold=float(spec.abnormal_return_threshold),
        require_adjustment=bool(spec.require_adjustment),
    )
    constituents = load_index_constituents()
    filtered, universe_mode = filter_investable_universe(
        feature_data,
        constituents=constituents if not constituents.empty else None,
        config=cfg,
        require_constituents=bool(spec.require_constituents),
        allow_fallback=bool(spec.allow_fallback),
    )
    if spec.target_index_codes and "index_pool_codes" in filtered.columns:
        wanted = {str(code).zfill(6) for code in spec.target_index_codes}
        mask = filtered["index_pool_codes"].fillna("").astype(str).map(
            lambda text: bool(wanted & {item.strip().zfill(6) for item in text.split(",") if item.strip()})
        )
        filtered = filtered[mask].copy()
    filtered["requested_universe_name"] = universe_name
    filtered["fast_factor_universe_mode"] = universe_mode
    return filtered


def _limit_recent_days(feature_data: pd.DataFrame, *, max_days: int | None) -> pd.DataFrame:
    if max_days is None or int(max_days) <= 0 or feature_data.empty:
        return feature_data
    dates = sorted(pd.to_datetime(feature_data["date"], errors="coerce").dropna().unique())
    keep = set(dates[-int(max_days):])
    return feature_data[feature_data["date"].isin(keep)].copy()


def _attach_cost_adjusted_metrics(validation: pd.DataFrame) -> pd.DataFrame:
    if validation is None or validation.empty:
        return validation
    data = validation.copy()
    turnover = pd.to_numeric(data.get("turnover_mean"), errors="coerce").fillna(0.0)
    spread = pd.to_numeric(data.get("top_bottom_spread"), errors="coerce")
    data["round_trip_cost_rate"] = _round_trip_cost_rate()
    data["turnover_cost_estimate"] = turnover * float(data["round_trip_cost_rate"].iloc[0])
    data["cost_adjusted_top_bottom_spread"] = spread - data["turnover_cost_estimate"]
    return data


def _stamp_report_metadata(
    reports: dict[str, pd.DataFrame],
    *,
    run_id: str,
    run_created_at: str,
    universe_name: str,
    analysis_start_date: str,
    analysis_end_date: str,
) -> dict[str, pd.DataFrame]:
    stamped: dict[str, pd.DataFrame] = {}
    metadata = {
        "run_id": run_id,
        "run_created_at": run_created_at,
        "universe_name": universe_name,
        "analysis_start_date": analysis_start_date,
        "analysis_end_date": analysis_end_date,
    }
    for name, frame in reports.items():
        if frame is None:
            stamped[name] = frame
            continue
        data = frame.copy()
        for column, value in metadata.items():
            data[column] = value
        front = [column for column in metadata if column in data.columns]
        stamped[name] = data.loc[:, front + [column for column in data.columns if column not in front]]
    return stamped


def _recent_start_date(feature_path: Path, *, max_days: int) -> str | None:
    try:
        dates = pd.read_parquet(feature_path, columns=["date"])
    except Exception:
        return None
    if dates.empty or "date" not in dates.columns:
        return None
    unique_dates = pd.to_datetime(dates["date"], errors="coerce").dropna().drop_duplicates().sort_values()
    if unique_dates.empty:
        return None
    cutoff_index = max(len(unique_dates) - int(max_days), 0)
    return unique_dates.iloc[cutoff_index].strftime("%Y-%m-%d")


def _parquet_date_filters(*, start_date: str | None, end_date: str | None):
    filters = []
    if start_date:
        filters.append(("date", ">=", pd.Timestamp(start_date)))
    if end_date:
        filters.append(("date", "<=", pd.Timestamp(end_date)))
    return filters or None


def _round_trip_cost_rate() -> float:
    return float(2.0 * COMMISSION_RATE + STAMP_DUTY_RATE + 2.0 * SLIPPAGE_RATE + 2.0 * TRANSFER_FEE_RATE)


def _emit_progress(progress_callback, **payload) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(payload)
    except Exception:
        return


def _factor_validation_progress(progress_callback):
    if progress_callback is None:
        return None

    def _callback(payload: dict) -> None:
        current = int(payload.get("current") or 0)
        total = max(int(payload.get("total") or 1), 1)
        inner = current / total
        _emit_progress(
            progress_callback,
            percent=25.0 + inner * 60.0,
            step="factor_validation",
            message=f"validating factor {current}/{total}",
            detail=str(payload.get("factor_name") or ""),
            current=current,
            total=total,
        )

    return _callback


def _safe_int(value, *, default: int = 0) -> int:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").dropna()
    if numeric.empty:
        return int(default)
    return int(numeric.iloc[0])


def _date_min(data: pd.DataFrame) -> str:
    if data is None or data.empty or "date" not in data.columns:
        return ""
    return str(pd.to_datetime(data["date"], errors="coerce").min().date())


def _date_max(data: pd.DataFrame) -> str:
    if data is None or data.empty or "date" not in data.columns:
        return ""
    return str(pd.to_datetime(data["date"], errors="coerce").max().date())
