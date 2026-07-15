"""Bounded, low-memory research for executable daily order-flow proxies."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd

from config import FEATURE_DAILY_PARQUET
from functions.factors.orderflow_parameter_factors import (
    append_parameterized_orderflow_factors,
    parameter_factor_specs,
)


OUTPUT_ROOT = Path("results/decision_council/orderflow_parameter_research")
HORIZONS = (3, 5, 10, 20)


def run_orderflow_parameter_research(
    *,
    feature_path: str | Path = FEATURE_DAILY_PARQUET,
    output_root: str | Path = OUTPUT_ROOT,
    start_date=None,
    end_date=None,
    max_days: int | None = None,
    max_variants: int | None = None,
    max_runtime_seconds: float = 1800.0,
    run_kind: str = "production",
    progress_callback=None,
) -> dict[str, Path]:
    started = time.monotonic()
    run_id = datetime.now().strftime("run%Y%m%d_%H%M%S_%f")
    output = Path(output_root) / run_id
    output.mkdir(parents=True, exist_ok=False)
    status_path = output / "artifact_manifest.json"
    _write_manifest(status_path, run_id=run_id, run_kind=run_kind, status="running")
    try:
        _emit_progress(progress_callback, percent=2.0, step="load_window", message="loading bounded feature window")
        data, analysis_dates = _load_window(
            Path(feature_path), start_date=start_date, end_date=end_date, max_days=max_days
        )
        specs = parameter_factor_specs()
        if max_variants is not None:
            specs = specs[: max(int(max_variants), 1)]
        _emit_progress(
            progress_callback,
            percent=8.0,
            step="evaluate_variants",
            message=f"evaluating {len(specs)} parameter variants",
            current=0,
            total=len(specs),
        )
        rows = []
        for index, spec in enumerate(specs, start=1):
            _check_deadline(started, max_runtime_seconds, detail=f"variant {index}/{len(specs)}")
            column = spec["raw_column"]
            work = append_parameterized_orderflow_factors(
                data, include_columns={column}, close_col=_close_column(data)
            )
            factor = _winsorize_by_date(work[column], work["date"])
            normalization = "winsorized"
            if {"sector_parent", "stabilized_float_cap"}.issubset(work.columns):
                factor = _neutralize(work, factor)
                normalization = "industry_size_neutralized"
            metrics = _evaluate(work, factor, analysis_dates=analysis_dates)
            for metric in metrics:
                rows.append({**spec, **metric, "normalization": normalization})
            del work, factor
            _emit_progress(
                progress_callback,
                percent=8.0 + 84.0 * index / max(len(specs), 1),
                step="evaluate_variants",
                message=str(spec.get("raw_column", "factor variant")),
                current=index,
                total=len(specs),
            )
        _emit_progress(progress_callback, percent=94.0, step="select_decisions", message="selecting parameter profiles")
        summary = pd.DataFrame(rows)
        decisions = _select_decisions(summary)
        summary.to_csv(output / "parameter_summary.csv", index=False, encoding="utf-8-sig")
        decisions.to_csv(output / "appeal_summary.csv", index=False, encoding="utf-8-sig")
        decisions[decisions["new_decision"].eq("promote_candidate")].to_csv(
            output / "admitted_v2.csv", index=False, encoding="utf-8-sig"
        )
        decisions[decisions["new_decision"].eq("watchlist")].to_csv(
            output / "watchlist_v2.csv", index=False, encoding="utf-8-sig"
        )
        _emit_progress(progress_callback, percent=98.0, step="save_artifacts", message="saving research artifacts")
        _write_manifest(
            status_path,
            run_id=run_id,
            run_kind=run_kind,
            status="complete",
            extra={
                "artifact_type": "orderflow_parameter_research",
                "variant_count": int(len(specs)),
                "analysis_date_count": int(len(analysis_dates)),
                "promoted_count": int(decisions["new_decision"].eq("promote_candidate").sum()),
                "elapsed_seconds": round(time.monotonic() - started, 3),
            },
        )
        return {
            "output_dir": output,
            "parameter_summary": output / "parameter_summary.csv",
            "appeal_summary": output / "appeal_summary.csv",
            "admitted_v2": output / "admitted_v2.csv",
            "artifact_manifest": status_path,
        }
    except Exception as exc:
        _write_manifest(
            status_path,
            run_id=run_id,
            run_kind=run_kind,
            status="failed",
            extra={"error": str(exc), "elapsed_seconds": round(time.monotonic() - started, 3)},
        )
        raise


def _emit_progress(progress_callback, **payload) -> None:
    if progress_callback is not None:
        progress_callback(payload)


def _load_window(path: Path, *, start_date=None, end_date=None, max_days=None):
    import pyarrow.parquet as pq

    available = set(pq.read_schema(path).names)
    wanted = [
        "date", "symbol", "open_nominal", "high_nominal", "low_nominal", "close_nominal",
        "open", "high", "low", "close", "amount", "volume", "sector_parent",
        "stabilized_float_cap", "instrument_type",
    ]
    columns = [column for column in wanted if column in available]
    if not {"date", "symbol", "amount", "volume"}.issubset(columns):
        raise ValueError("Orderflow parameter research input is missing date/symbol/amount/volume")
    filters = []
    start_ts = pd.Timestamp(start_date) if start_date else None
    end_ts = pd.Timestamp(end_date) if end_date else None
    if start_ts is not None and max_days is not None:
        bounded_end = start_ts + pd.Timedelta(days=max(int(max_days), 1) * 2 + 30)
        end_ts = min(end_ts, bounded_end) if end_ts is not None else bounded_end
    if start_ts is not None:
        filters.append(("date", ">=", start_ts - pd.Timedelta(days=120)))
    if end_ts is not None:
        filters.append(("date", "<=", end_ts + pd.Timedelta(days=35)))
    data = pd.read_parquet(path, columns=columns, filters=filters or None)
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data = data.dropna(subset=["date", "symbol"]).sort_values(["symbol", "date"])
    dates = pd.Index(sorted(data["date"].dropna().unique()))
    analysis = dates
    if start_ts is not None:
        analysis = analysis[analysis >= start_ts]
    if end_ts is not None:
        analysis = analysis[analysis <= end_ts]
    if max_days is not None:
        analysis = analysis[: max(int(max_days), 1)]
    if len(analysis) == 0:
        raise ValueError("No analysis dates are available for orderflow parameter research")
    return data, set(pd.Timestamp(item) for item in analysis)


def _evaluate(data: pd.DataFrame, factor: pd.Series, *, analysis_dates: set[pd.Timestamp]) -> list[dict]:
    close = pd.to_numeric(data[_close_column(data)], errors="coerce")
    grouped_close = close.groupby(data["symbol"], sort=False)
    rows = []
    for horizon in HORIZONS:
        future = grouped_close.shift(-horizon) / close.replace(0.0, np.nan) - 1.0
        work = pd.DataFrame({"date": data["date"], "symbol": data["symbol"], "factor": factor, "future": future})
        analysis_mask = work["date"].isin(analysis_dates)
        analysis_row_count = int(analysis_mask.sum())
        work = work[analysis_mask].dropna(subset=["factor", "future"])
        daily_ic, daily_spread, top_sets = [], [], []
        for date, day in work.groupby("date", sort=True):
            if len(day) < 30 or day["factor"].nunique() < 3:
                continue
            ranked = day["factor"].rank(pct=True)
            daily_ic.append(ranked.corr(day["future"].rank(pct=True)))
            top = day.loc[ranked >= 0.8]
            bottom = day.loc[ranked <= 0.2]
            daily_spread.append(float(top["future"].mean() - bottom["future"].mean()))
            top_sets.append(set(top["symbol"].astype(str)))
        ic = pd.Series(daily_ic, dtype=float).dropna()
        spread = pd.Series(daily_spread, dtype=float).dropna()
        turnover = _average_turnover(top_sets)
        spread_mean = float(spread.mean()) if not spread.empty else np.nan
        rows.append({
            "horizon_days": horizon,
            "rank_ic": float(ic.mean()) if not ic.empty else np.nan,
            "ic_ir": float(ic.mean() / ic.std(ddof=0)) if len(ic) > 1 and ic.std(ddof=0) > 0 else np.nan,
            "positive_ic_ratio": float((ic > 0).mean()) if not ic.empty else np.nan,
            "top_bottom_spread": spread_mean,
            "avg_turnover": turnover,
            "cost_adjusted_top_bottom_spread": spread_mean - turnover * 0.0015 if pd.notna(spread_mean) else np.nan,
            "coverage": float(len(work) / max(analysis_row_count, 1)),
            "sample_count": int(len(work)),
        })
    return rows


def _select_decisions(summary: pd.DataFrame) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame()
    ranked = summary.copy()
    ranked["research_score"] = (
        pd.to_numeric(ranked["rank_ic"], errors="coerce").fillna(-1.0)
        + 0.5 * pd.to_numeric(ranked["ic_ir"], errors="coerce").fillna(-1.0)
        + 10.0 * pd.to_numeric(ranked["cost_adjusted_top_bottom_spread"], errors="coerce").fillna(-1.0)
    )
    best = ranked.sort_values("research_score", ascending=False).groupby("economic_family", as_index=False).head(1).copy()
    breakout = best["factor_family"].eq("breakout")
    passed = np.where(
        breakout,
        best["rank_ic"].ge(0.02) & best["ic_ir"].ge(0.10) & best["top_bottom_spread"].gt(0.0),
        best["rank_ic"].ge(0.005) & best["ic_ir"].ge(0.05) & best["cost_adjusted_top_bottom_spread"].gt(0.0),
    )
    near = best["rank_ic"].ge(0.003) & best["ic_ir"].ge(0.03)
    best["new_decision"] = np.where(passed, "promote_candidate", np.where(near, "watchlist", "reject_or_rework"))
    best["new_role"] = best["role"]
    best["factor_type"] = best["factor_family"]
    best["old_decision"] = "parameter_research"
    best["old_role"] = "not_applicable"
    best["promote_reason"] = np.where(passed, "cost_adjusted_parameter_profile_pass", "")
    best["watchlist_reason"] = np.where(~passed & near, "near_pass_parameter_profile", "")
    best["reject_reason"] = np.where(~passed & ~near, "parameter_profile_failed", "")
    best["event_count"] = best["sample_count"]
    best["win_rate"] = best["positive_ic_ratio"]
    best["avg_excess_return"] = best["top_bottom_spread"]
    return best.reset_index(drop=True)


def _winsorize_by_date(values: pd.Series, dates: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    lower = numeric.groupby(dates, sort=False).transform(lambda s: s.quantile(0.01))
    upper = numeric.groupby(dates, sort=False).transform(lambda s: s.quantile(0.99))
    return numeric.clip(lower=lower, upper=upper)


def _neutralize(data: pd.DataFrame, values: pd.Series) -> pd.Series:
    industry_mean = values.groupby([data["date"], data["sector_parent"]], sort=False).transform("mean")
    size = np.log1p(pd.to_numeric(data["stabilized_float_cap"], errors="coerce").where(lambda s: s > 0.0))
    size_centered = size - size.groupby(data["date"], sort=False).transform("mean")
    return values - industry_mean - size_centered.fillna(0.0)


def _average_turnover(top_sets: list[set[str]]) -> float:
    values = []
    for previous, current in zip(top_sets, top_sets[1:]):
        denominator = max(len(previous), len(current), 1)
        values.append(1.0 - len(previous & current) / denominator)
    return float(np.mean(values)) if values else 0.0


def _close_column(data: pd.DataFrame) -> str:
    return "close_nominal" if "close_nominal" in data.columns else "close"


def _check_deadline(started: float, limit: float, *, detail: str) -> None:
    if limit > 0 and time.monotonic() - started > limit:
        raise TimeoutError(f"Orderflow parameter research exceeded {limit:.0f}s at {detail}")


def _write_manifest(path: Path, *, run_id: str, run_kind: str, status: str, extra: dict | None = None) -> None:
    payload = {
        "artifact_type": "orderflow_parameter_research",
        "artifact_version": "daily_ohlcv_proxy_grid_v1",
        "run_id": run_id,
        "run_kind": str(run_kind),
        "status": status,
        **(extra or {}),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
