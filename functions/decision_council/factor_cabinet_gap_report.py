"""Gap and redundancy audit for factor-cabinet runs.

This module is intentionally read-only: it does not create factors and does not
modify state-machine or trading behavior.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import FEATURE_DAILY_PARQUET
from functions.decision_council.factor_cabinet_feature_cache import (
    _factor_cabinet_raw_columns,
    find_factor_cabinet_feature_cache,
)
from functions.decision_council.factor_source import (
    FACTOR_SOURCE_LATEST_CABINET,
    FactorSourceSpec,
    resolve_factor_source,
)


REPORT_ROOT = Path("results/factor_cabinet_gap_report")
TARGET_ROLE_RANGES = {
    "entry_alpha": (15, 25),
    "entry_alpha_proxy": (0, 15),
    "timing_filter": (15, 25),
    "risk_override": (15, 25),
    "liquidity_filter": (10, 15),
    "hold_validation": (10, 20),
}
EXPECTED_FAMILIES = ("rsi", "growth", "profit", "roe", "roa", "cash", "ocf", "event", "announcement")


def build_factor_cabinet_gap_report(
    *,
    factor_source: str = FACTOR_SOURCE_LATEST_CABINET,
    factor_cabinet_run_id: str = "",
    factor_cabinet_path: str = "",
    start_date=None,
    end_date=None,
    sample_rows: int = 40_000,
    sample_days: int = 48,
    top_quantile: float = 0.2,
    require_cache_metrics: bool = False,
    output_root: str | Path = REPORT_ROOT,
    progress_callback=None,
) -> dict[str, Path]:
    """Build a compact cabinet audit from metadata and optional materialized cache."""
    def progress(step: str, percent: float, detail: str = "") -> None:
        if progress_callback is not None:
            progress_callback({"step": step, "percent": float(percent), "detail": detail})
        print(f"[factor_cabinet_gap_report] {step}: {detail}", flush=True)

    progress("resolve_factor_cabinet", 5.0)
    spec = resolve_factor_source(
        factor_source=factor_source,
        factor_cabinet_run_id=factor_cabinet_run_id,
        factor_cabinet_path=factor_cabinet_path,
    )
    if not spec.uses_factor_cabinet:
        raise ValueError("factor_cabinet gap report requires latest_factor_cabinet or selected_factor_cabinet")
    cabinet = _load_cabinet_frame(spec)
    run_dir = Path(output_root) / spec.factor_cabinet_run_id / datetime.now().strftime("run%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    progress("structure_reports", 15.0, f"factors={len(cabinet)}")
    structure = _build_structure_report(cabinet)
    family = _build_family_report(cabinet)
    near_relative = _build_near_relative_report(cabinet)
    role_gap = _build_role_gap_report(structure)
    missing_family = _build_missing_family_report(cabinet)

    saved: dict[str, Path] = {}
    saved["cabinet_structure"] = _write_csv(structure, run_dir / "cabinet_structure.csv")
    saved["cabinet_family_concentration"] = _write_csv(family, run_dir / "cabinet_family_concentration.csv")
    saved["cabinet_near_relative_concentration"] = _write_csv(
        near_relative, run_dir / "cabinet_near_relative_concentration.csv"
    )
    saved["cabinet_role_gap"] = _write_csv(role_gap, run_dir / "cabinet_role_gap.csv")
    saved["cabinet_missing_family_gap"] = _write_csv(missing_family, run_dir / "cabinet_missing_family_gap.csv")

    corr = pd.DataFrame()
    overlap = pd.DataFrame()
    cache_status: dict = {"status": "not_requested"}
    if start_date is not None and end_date is not None:
        try:
            progress("load_sampled_feature_cache", 35.0, f"sample_rows={sample_rows}, sample_days={sample_days}")
            sample, raw_columns, cache_status = _load_sampled_cache(
                spec,
                start_date,
                end_date,
                sample_rows=sample_rows,
                sample_days=sample_days,
            )
            progress("correlation_report", 60.0, f"rows={len(sample)}, raw_columns={len(raw_columns)}")
            corr = _build_correlation_report(sample, raw_columns)
            progress("top_overlap_report", 78.0, f"rows={len(sample)}, raw_columns={len(raw_columns)}")
            overlap = _build_top_overlap_report(sample, raw_columns, top_quantile=top_quantile)
        except Exception as exc:
            if require_cache_metrics:
                raise RuntimeError(
                    "factor_cabinet gap audit requires a current feature cache; "
                    "run 'factor_cabinet feature cache/materialization' for this exact cabinet first. "
                    f"Reason: {exc}"
                ) from exc
            cache_status = {"status": "skipped_cache_metrics", "reason": str(exc)}
    saved["factor_value_spearman_corr"] = _write_csv(corr, run_dir / "factor_value_spearman_corr.csv")
    saved["top_quantile_overlap"] = _write_csv(overlap, run_dir / "top_quantile_overlap.csv")

    summary = _build_summary(
        spec=spec,
        structure=structure,
        family=family,
        near_relative=near_relative,
        role_gap=role_gap,
        missing_family=missing_family,
        corr=corr,
        overlap=overlap,
        cache_status=cache_status,
    )
    progress("write_summary", 92.0, f"run_dir={run_dir}")
    summary_path = run_dir / "factor_cabinet_gap_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    saved["summary"] = summary_path
    saved["report"] = _write_report(summary, run_dir / "factor_cabinet_gap_report.md")
    progress("complete", 100.0, f"run_dir={run_dir}")
    return saved


def _load_cabinet_frame(spec: FactorSourceSpec) -> pd.DataFrame:
    payload = json.loads(Path(spec.factor_cabinet_path).read_text(encoding="utf-8"))
    frame = pd.DataFrame(payload.get("factors", []))
    if frame.empty:
        raise ValueError(f"factor_cabinet has no factors: {spec.factor_cabinet_path}")
    if "role" not in frame.columns and "cabinet_role" in frame.columns:
        frame["role"] = frame["cabinet_role"]
    for column in ("factor_name", "raw_column", "role", "family", "module", "near_relative_key", "source"):
        if column not in frame.columns:
            frame[column] = ""
        frame[column] = frame[column].fillna("").astype(str)
    return frame


def _build_structure_report(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    total = max(len(frame), 1)
    for role, group in frame.groupby("role", dropna=False):
        rows.append(
            {
                "role": role or "missing",
                "factor_count": int(len(group)),
                "share": float(len(group) / total),
                "module_count": int(group["module"].nunique()),
                "family_count": int(group["family"].nunique()),
                "near_relative_count": int(group["near_relative_key"].nunique()),
            }
        )
    return pd.DataFrame(rows).sort_values(["factor_count", "role"], ascending=[False, True])


def _build_family_report(frame: pd.DataFrame) -> pd.DataFrame:
    total = max(len(frame), 1)
    data = (
        frame.groupby(["role", "family"], dropna=False)
        .agg(
            factor_count=("factor_name", "count"),
            module_count=("module", "nunique"),
            near_relative_count=("near_relative_key", "nunique"),
        )
        .reset_index()
    )
    data["share_of_total"] = data["factor_count"] / total
    data["share_within_role"] = data["factor_count"] / data.groupby("role")["factor_count"].transform("sum")
    return data.sort_values(["share_of_total", "factor_count"], ascending=[False, False])


def _build_near_relative_report(frame: pd.DataFrame) -> pd.DataFrame:
    data = (
        frame.groupby(["role", "near_relative_key"], dropna=False)
        .agg(
            factor_count=("factor_name", "count"),
            families=("family", lambda values: "|".join(sorted(set(str(v) for v in values if str(v))))),
            sample_factors=("factor_name", lambda values: "|".join(list(values.astype(str).head(5)))),
        )
        .reset_index()
    )
    return data.sort_values(["factor_count", "role"], ascending=[False, True])


def _build_role_gap_report(structure: pd.DataFrame) -> pd.DataFrame:
    by_role = {str(row["role"]): int(row["factor_count"]) for _, row in structure.iterrows()}
    rows = []
    for role, (minimum, maximum) in TARGET_ROLE_RANGES.items():
        count = int(by_role.get(role, 0))
        rows.append(
            {
                "role": role,
                "factor_count": count,
                "target_min": minimum,
                "target_max": maximum,
                "status": "below_target" if count < minimum else "above_target" if count > maximum else "ok",
                "gap_to_min": max(minimum - count, 0),
                "excess_over_max": max(count - maximum, 0),
            }
        )
    return pd.DataFrame(rows)


def _build_missing_family_report(frame: pd.DataFrame) -> pd.DataFrame:
    text = " ".join(
        frame[["factor_name", "raw_column", "family", "module"]]
        .fillna("")
        .astype(str)
        .agg(" ".join, axis=1)
        .tolist()
    ).lower()
    rows = []
    for family in EXPECTED_FAMILIES:
        rows.append(
            {
                "expected_family": family,
                "present": bool(family in text),
                "status": "present" if family in text else "missing_or_not_integrated",
            }
        )
    return pd.DataFrame(rows)


def _sample_cache(cache: pd.DataFrame, raw_columns: list[str], *, sample_rows: int) -> pd.DataFrame:
    columns = ["date", "symbol"] + list(raw_columns)
    sample = cache.loc[:, columns].copy()
    sample = sample.dropna(subset=["date", "symbol"])
    if len(sample) > int(sample_rows):
        sample = sample.sample(n=int(sample_rows), random_state=7)
    return sample


def _load_sampled_cache(
    spec: FactorSourceSpec,
    start_date,
    end_date,
    *,
    sample_rows: int,
    sample_days: int,
) -> tuple[pd.DataFrame, list[str], dict]:
    found, status = find_factor_cabinet_feature_cache(spec, start_date, end_date, feature_path=FEATURE_DAILY_PARQUET)
    if found is None:
        raise FileNotFoundError(f"factor_cabinet feature cache is required for cache metrics. Detail: {status}")
    parquet_path, _manifest = found
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    index = pd.read_parquet(
        parquet_path,
        columns=["date", "symbol"],
        filters=[("date", ">=", start_ts), ("date", "<=", end_ts)],
    )
    index["date"] = pd.to_datetime(index["date"], errors="coerce")
    index = index.dropna(subset=["date", "symbol"])
    raw_columns = list(_factor_cabinet_raw_columns(spec))
    if index.empty:
        return pd.DataFrame(columns=["date", "symbol", *raw_columns]), raw_columns, {
            "status": "loaded_empty_sample",
            "rows": 0,
            "sample_rows": 0,
            "raw_columns": int(len(raw_columns)),
        }
    dates = pd.Index(index["date"].dropna().sort_values().unique())
    target_days = min(max(int(sample_days), 1), len(dates))
    positions = pd.Series(range(len(dates))).sample(n=target_days, random_state=7).sort_values().tolist()
    selected_dates = [pd.Timestamp(dates[int(pos)]) for pos in positions]
    sample = pd.read_parquet(
        parquet_path,
        columns=["date", "symbol", *raw_columns],
        filters=[("date", "in", selected_dates)],
    )
    sample["date"] = pd.to_datetime(sample["date"], errors="coerce")
    sample = sample.dropna(subset=["date", "symbol"])
    sample = _sample_cache(sample, raw_columns, sample_rows=sample_rows)
    return sample, raw_columns, {
        "status": "loaded_sampled",
        "rows": int(len(index)),
        "sample_rows": int(len(sample)),
        "sample_days": int(target_days),
        "raw_columns": int(len(raw_columns)),
        "start_date": start_ts.strftime("%Y-%m-%d"),
        "end_date": end_ts.strftime("%Y-%m-%d"),
    }


def _build_correlation_report(sample: pd.DataFrame, raw_columns: list[str]) -> pd.DataFrame:
    if sample.empty or len(raw_columns) < 2:
        return pd.DataFrame(columns=["factor_a", "factor_b", "spearman_corr", "abs_corr"])
    numeric = sample[raw_columns].apply(pd.to_numeric, errors="coerce")
    corr = numeric.corr(method="spearman", min_periods=max(50, min(500, len(numeric) // 20)))
    rows = []
    for i, left in enumerate(raw_columns):
        for right in raw_columns[i + 1 :]:
            value = corr.loc[left, right]
            if pd.notna(value):
                rows.append(
                    {
                        "factor_a": left,
                        "factor_b": right,
                        "spearman_corr": float(value),
                        "abs_corr": float(abs(value)),
                    }
                )
    return pd.DataFrame(rows).sort_values("abs_corr", ascending=False) if rows else pd.DataFrame()


def _build_top_overlap_report(sample: pd.DataFrame, raw_columns: list[str], *, top_quantile: float) -> pd.DataFrame:
    if sample.empty or len(raw_columns) < 2:
        return pd.DataFrame(columns=["factor_a", "factor_b", "avg_top_overlap"])
    rows = []
    for date, day in sample.groupby("date", sort=False):
        if len(day) < 30:
            continue
        top_sets = {}
        cutoff_n = max(int(len(day) * float(top_quantile)), 1)
        for column in raw_columns:
            values = pd.to_numeric(day[column], errors="coerce")
            valid = day.loc[values.notna(), ["symbol"]].copy()
            if len(valid) < 30:
                continue
            valid["_value"] = values[values.notna()].to_numpy()
            top_sets[column] = set(valid.nlargest(min(cutoff_n, len(valid)), "_value")["symbol"].astype(str))
        columns = sorted(top_sets)
        for i, left in enumerate(columns):
            for right in columns[i + 1 :]:
                denom = max(min(len(top_sets[left]), len(top_sets[right])), 1)
                rows.append(
                    {
                        "date": date,
                        "factor_a": left,
                        "factor_b": right,
                        "top_overlap": len(top_sets[left] & top_sets[right]) / denom,
                    }
                )
    if not rows:
        return pd.DataFrame(columns=["factor_a", "factor_b", "avg_top_overlap", "observed_days"])
    data = pd.DataFrame(rows)
    return (
        data.groupby(["factor_a", "factor_b"], as_index=False)
        .agg(avg_top_overlap=("top_overlap", "mean"), observed_days=("date", "nunique"))
        .sort_values("avg_top_overlap", ascending=False)
    )


def _build_summary(
    *,
    spec: FactorSourceSpec,
    structure: pd.DataFrame,
    family: pd.DataFrame,
    near_relative: pd.DataFrame,
    role_gap: pd.DataFrame,
    missing_family: pd.DataFrame,
    corr: pd.DataFrame,
    overlap: pd.DataFrame,
    cache_status: dict,
) -> dict:
    top_family_share = float(family["share_of_total"].max()) if not family.empty else 0.0
    duplicate_near_relative_groups = int((near_relative["factor_count"] > 1).sum()) if not near_relative.empty else 0
    high_corr_pairs = int((corr.get("abs_corr", pd.Series(dtype=float)) > 0.75).sum()) if not corr.empty else 0
    high_overlap_pairs = int((overlap.get("avg_top_overlap", pd.Series(dtype=float)) > 0.60).sum()) if not overlap.empty else 0
    missing = missing_family.loc[~missing_family["present"], "expected_family"].astype(str).tolist()
    recommendations = []
    if "entry_alpha" in set(role_gap.loc[role_gap["status"].eq("below_target"), "role"]):
        recommendations.append("strict entry_alpha is below target; treat proxy_entry_alpha as temporary evidence only")
    if top_family_share > 0.15:
        recommendations.append("family concentration is high; run family and near-relative pruning before expanding cabinet")
    if duplicate_near_relative_groups:
        recommendations.append("near-relative duplicates remain; keep one representative per duplicate key")
    if high_corr_pairs or high_overlap_pairs:
        recommendations.append("highly redundant pairs exist; prune by correlation and top-overlap before production review")
    if missing:
        recommendations.append("missing composite families should be researched only after PIT data is verified: " + ", ".join(missing))
    return {
        "artifact_type": "factor_cabinet_gap_report",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "factor_source": spec.factor_source,
        "factor_cabinet_run_id": spec.factor_cabinet_run_id,
        "factor_cabinet_path": spec.factor_cabinet_path,
        "factor_count": int(spec.factor_count),
        "role_distribution": spec.role_distribution or {},
        "top_family_share": top_family_share,
        "duplicate_near_relative_groups": duplicate_near_relative_groups,
        "high_corr_pairs_abs_gt_075": high_corr_pairs,
        "high_top_overlap_pairs_gt_060": high_overlap_pairs,
        "missing_expected_families": missing,
        "cache_status": cache_status,
        "recommendations": recommendations,
    }


def _write_csv(frame: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _write_report(summary: dict, path: Path) -> Path:
    lines = [
        "# Factor Cabinet Gap Report",
        "",
        f"- run_id: {summary['factor_cabinet_run_id']}",
        f"- factor_count: {summary['factor_count']}",
        f"- top_family_share: {summary['top_family_share']:.2%}",
        f"- duplicate_near_relative_groups: {summary['duplicate_near_relative_groups']}",
        f"- high_corr_pairs_abs_gt_075: {summary['high_corr_pairs_abs_gt_075']}",
        f"- high_top_overlap_pairs_gt_060: {summary['high_top_overlap_pairs_gt_060']}",
        f"- missing_expected_families: {', '.join(summary['missing_expected_families']) or 'none'}",
        f"- cache_status: {summary['cache_status'].get('status')}",
        "",
        "## Recommendations",
        "",
    ]
    lines.extend(f"- {item}" for item in summary.get("recommendations", []))
    if not summary.get("recommendations"):
        lines.append("- No structural gap above configured thresholds.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
