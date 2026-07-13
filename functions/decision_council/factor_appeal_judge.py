"""Factor Judge v2 appeal flow.

The appeal judge never overwrites v1 fast-factor-judge outputs. It reads v1 as
the first-pass filter, applies profile-specific rules to selected families, and
writes separate v2 outputs for the factor cabinet builder.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json

import numpy as np
import pandas as pd

from config import FEATURE_DAILY_PARQUET
from functions.decision_council.factor_judge_profiles import (
    build_profile_mapping_report,
    load_factor_judge_profiles,
    map_factor_to_profile,
)
from functions.decision_council.factor_pool_contract import load_factor_pool_contract
from functions.decision_council.factor_registry import build_factor_registry
from functions.decision_council.factor_validation import build_factor_research_reports
from functions.factors.technical_timing_factors import append_rsi_timing_factors, rsi_timing_registry_rows


DEFAULT_V1_RUN_DIR = Path(
    "results/decision_council/fast_factor_judge/"
    "hs300_csi500_a500_strict/run20260705_180001_095951"
)
APPEAL_OUTPUT_ROOT = Path("results/decision_council/factor_appeal_judge")
APPEAL_TARGET_FAMILIES = {
    "rsi",
    "growth",
    "profitability",
    "cashflow",
    "quality",
    "valuation",
    "event",
    "alternative_proxy",
    "orderflow_proxy",
    "breakout",
}


def run_factor_appeal_judge(
    *,
    v1_run_dir: str | Path = DEFAULT_V1_RUN_DIR,
    output_root: str | Path = APPEAL_OUTPUT_ROOT,
    feature_path: str | Path = FEATURE_DAILY_PARQUET,
    families: set[str] | None = None,
    max_days: int | None = None,
    run_kind: str = "production",
) -> dict[str, Path]:
    v1_dir = Path(v1_run_dir)
    summary_path = v1_dir / "fast_factor_summary.csv"
    manifest_path = v1_dir / "fast_factor_judge_manifest.csv"
    if not summary_path.exists():
        raise FileNotFoundError(f"v1 fast factor summary not found: {summary_path}")
    run_id = datetime.now().strftime("run%Y%m%d_%H%M%S_%f")
    output = Path(output_root) / run_id
    output.mkdir(parents=True, exist_ok=False)

    profiles = load_factor_judge_profiles()
    v1_contract = load_factor_pool_contract(summary_path)
    mapping_report, unmapped = build_profile_mapping_report(v1_contract, profiles=profiles)
    mapping_report.to_csv(output / "profile_mapping_report.csv", index=False, encoding="utf-8-sig")
    unmapped.to_csv(output / "unmapped_factors.csv", index=False, encoding="utf-8-sig")

    target_families = set(families or APPEAL_TARGET_FAMILIES)
    appeal_parts = []
    if "rsi" in target_families:
        appeal_parts.append(_run_rsi_appeal(v1_dir, feature_path=Path(feature_path), profiles=profiles, max_days=max_days))
    if target_families.intersection({"orderflow_proxy", "breakout"}):
        appeal_parts.append(
            _run_flow_breakout_appeal(
                v1_dir,
                include_orderflow="orderflow_proxy" in target_families,
                include_breakout="breakout" in target_families,
            )
        )
    nonempty_parts = [part.dropna(axis=1, how="all") for part in appeal_parts if part is not None and not part.empty]
    appeal = pd.concat(nonempty_parts, ignore_index=True) if nonempty_parts else _empty_appeal_summary()
    if appeal.empty:
        appeal = _empty_appeal_summary()
    appeal["v1_run_dir"] = str(v1_dir)
    appeal["appeal_run_id"] = run_id
    appeal = appeal[_appeal_columns()]
    appeal.to_csv(output / "appeal_summary.csv", index=False, encoding="utf-8-sig")
    _write_split_outputs(appeal, output)
    _write_distribution_outputs(appeal, output)
    _write_pending_family_report(target_families, appeal, output)
    _write_manifest(v1_dir, manifest_path, output, run_id)
    (output / "appeal_report.md").write_text(_render_appeal_report(appeal, output), encoding="utf-8")
    artifact_manifest = output / "artifact_manifest.json"
    artifact_manifest.write_text(
        json.dumps(
            {
                "artifact_type": "factor_appeal_judge",
                "artifact_version": "v3_role_aware_rsi_orderflow_breakout",
                "run_id": run_id,
                "run_kind": str(run_kind or "production").strip().lower(),
                "status": "complete",
                "v1_run_dir": str(v1_dir),
                "appeal_row_count": int(len(appeal)),
                "promoted_count": int(appeal["new_decision"].eq("promote_candidate").sum()),
                "watchlist_count": int(appeal["new_decision"].eq("watchlist").sum()),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "output_dir": output,
        "appeal_summary": output / "appeal_summary.csv",
        "admitted_v2": output / "admitted_v2.csv",
        "watchlist_v2": output / "watchlist_v2.csv",
        "rejected_v2": output / "rejected_v2.csv",
        "profile_mapping_report": output / "profile_mapping_report.csv",
        "unmapped_factors": output / "unmapped_factors.csv",
        "appeal_report": output / "appeal_report.md",
        "artifact_manifest": artifact_manifest,
    }


def _run_rsi_appeal(v1_dir: Path, *, feature_path: Path, profiles: dict, max_days: int | None = None) -> pd.DataFrame:
    profile = profiles["technical_timing"]
    manifest = _read_manifest(v1_dir / "fast_factor_judge_manifest.csv")
    start_date = manifest.get("analysis_start_date") or None
    end_date = manifest.get("analysis_end_date") or None
    data = _load_feature_window(feature_path, start_date=start_date, end_date=end_date, max_days=max_days)
    data = append_rsi_timing_factors(data, close_col="close_nominal" if "close_nominal" in data.columns else "close")
    registry = {}
    metrics = profile.metrics
    for row in rsi_timing_registry_rows():
        registry[row["factor_name"]] = {
            **row,
            "horizons": "|".join(str(item) for item in profile.horizons),
            "min_coverage": float(metrics.get("require_coverage", 0.50)),
            "min_abs_rank_ic": float(metrics.get("min_rank_ic_abs", 0.010)),
            "min_ic_ir": float(metrics.get("min_ic_ir", 0.12)),
            "min_rank_ic_positive_ratio": float(metrics.get("min_positive_ic_ratio", 0.50)),
            "min_top_bottom_spread_10d": -999.0,
            "min_sample_count": 500,
        }
    reports = build_factor_research_reports(
        data,
        registry=registry,
        horizons=profile.horizons,
        emit_quantile_rows=False,
        cluster_max_factors=0,
    )
    validation = reports.get("governance_factor_validation_report", pd.DataFrame())
    return _summarize_appeal_validation(
        validation,
        registry=registry,
        judge_profile=profile.name,
        factor_type="rsi",
        old_decision_lookup=_old_decision_lookup(v1_dir / "fast_factor_summary.csv"),
    )


def _summarize_appeal_validation(
    validation: pd.DataFrame,
    *,
    registry: dict,
    judge_profile: str,
    factor_type: str,
    old_decision_lookup: dict[str, str],
) -> pd.DataFrame:
    rows = []
    if validation is None or validation.empty:
        return _empty_appeal_summary()
    data = validation.copy()
    data["pass_flag"] = data.get("pass_flag", False).fillna(False).astype(bool)
    for factor_name, group in data.groupby("factor_name", sort=True):
        group = group.copy()
        ranked = group.sort_values(["pass_flag", "ic_ir", "rank_ic_mean"], ascending=[False, False, False])
        best = ranked.iloc[0]
        pass_count = int(group["pass_flag"].sum())
        if pass_count >= 1:
            decision = "promote_candidate"
            promote_reason = "technical_timing_profile_pass"
            watchlist_reason = ""
            reject_reason = ""
        elif _near_pass(group):
            decision = "watchlist"
            promote_reason = ""
            watchlist_reason = "near_pass_under_technical_timing_profile"
            reject_reason = ""
        else:
            decision = "reject_or_rework"
            promote_reason = ""
            watchlist_reason = ""
            reject_reason = str(best.get("fail_reasons", "failed_validation"))
        meta = registry.get(factor_name, {})
        rows.append(
            {
                "factor_name": factor_name,
                "raw_column": meta.get("raw_column", ""),
                "direction": meta.get("direction", "higher_better"),
                "parameter_version": "rsi_timing_v1",
                "factor_family": meta.get("family", factor_type),
                "factor_type": factor_type,
                "judge_profile": judge_profile,
                "old_decision": old_decision_lookup.get(factor_name, "not_in_v1"),
                "new_decision": decision,
                "old_role": "entry_alpha_if_used_in_v1",
                "new_role": _final_role_for_factor(factor_name, meta, decision),
                "rank_ic": best.get("rank_ic_mean", np.nan),
                "ic_ir": best.get("ic_ir", np.nan),
                "positive_ic_ratio": best.get("rank_ic_positive_ratio", np.nan),
                "top_bottom_spread": best.get("top_bottom_spread", np.nan),
                "coverage": best.get("coverage_ratio", np.nan),
                "event_count": pd.NA,
                "win_rate": pd.NA,
                "avg_excess_return": pd.NA,
                "reject_reason": reject_reason,
                "promote_reason": promote_reason,
                "watchlist_reason": watchlist_reason,
            }
        )
    return pd.DataFrame(rows)


def _run_flow_breakout_appeal(
    v1_dir: Path,
    *,
    include_orderflow: bool,
    include_breakout: bool,
) -> pd.DataFrame:
    """Rejudge existing executable columns with role-appropriate thresholds."""
    validation_path = v1_dir / "fast_factor_validation_report.csv"
    summary_path = v1_dir / "fast_factor_summary.csv"
    if not validation_path.exists() or not summary_path.exists():
        return _empty_appeal_summary()
    names = set()
    if include_orderflow:
        names.update({
            "orderflow_amount_shock",
            "orderflow_close_drive",
            "orderflow_accumulation",
            "orderflow_efficiency",
        })
    if include_breakout:
        names.update({"price_volume_breakout", "turtle_breakout"})
    validation = pd.read_csv(validation_path)
    validation = validation[validation["factor_name"].astype(str).isin(names)].copy()
    summary = pd.read_csv(summary_path)
    summary = summary[summary["factor_name"].astype(str).isin(names)].copy()
    summary_lookup = summary.set_index("factor_name").to_dict("index") if not summary.empty else {}
    registry = build_factor_registry()
    rows = []
    for factor_name, group in validation.groupby("factor_name", sort=True):
        meta = registry.get(str(factor_name), {})
        direction = str(meta.get("direction", "higher_better"))
        sign = -1.0 if direction == "lower_better" else 1.0
        work = group.copy()
        for column in ("rank_ic_mean", "top_bottom_spread", "cost_adjusted_top_bottom_spread"):
            work[column] = pd.to_numeric(work.get(column), errors="coerce") * sign
        positive = pd.to_numeric(work.get("rank_ic_positive_ratio"), errors="coerce")
        if sign < 0:
            work["rank_ic_positive_ratio"] = 1.0 - positive
        work["ic_ir"] = pd.to_numeric(work.get("ic_ir"), errors="coerce")
        work["coverage_ratio"] = pd.to_numeric(work.get("coverage_ratio"), errors="coerce")
        work = work.sort_values(
            ["ic_ir", "rank_ic_mean", "cost_adjusted_top_bottom_spread"],
            ascending=[False, False, False],
        )
        best = work.iloc[0]
        is_breakout = "breakout" in str(factor_name)
        if is_breakout:
            passed = bool(
                best["rank_ic_mean"] >= 0.030
                and best["ic_ir"] >= 0.12
                and best["rank_ic_positive_ratio"] >= 0.55
                and best["top_bottom_spread"] > 0.0
            )
            near = bool(best["rank_ic_mean"] >= 0.020 and best["ic_ir"] >= 0.10)
            role = "timing_filter"
            profile = "technical_timing_sparse"
            family = "breakout"
        else:
            passed = bool(
                best["rank_ic_mean"] >= 0.005
                and best["ic_ir"] >= 0.05
                and best["rank_ic_positive_ratio"] >= 0.50
                and best["cost_adjusted_top_bottom_spread"] > 0.0
            )
            near = bool(best["rank_ic_mean"] >= 0.004 and best["ic_ir"] >= 0.035)
            role = "liquidity_filter"
            profile = "price_fast_orderflow"
            family = "orderflow"
        decision = "promote_candidate" if passed else ("watchlist" if near else "reject_or_rework")
        old = summary_lookup.get(str(factor_name), {})
        rows.append({
            "factor_name": str(factor_name),
            "raw_column": str(meta.get("raw_column", old.get("raw_column", ""))),
            "direction": direction,
            "parameter_version": "existing_formula_direction_fixed_v1",
            "factor_family": family,
            "factor_type": "breakout" if is_breakout else "orderflow_proxy",
            "judge_profile": profile,
            "old_decision": str(old.get("verdict", "not_in_v1")),
            "new_decision": decision,
            "old_role": "entry_alpha_if_used_in_v1",
            "new_role": role if decision != "reject_or_rework" else "rejected",
            "rank_ic": best.get("rank_ic_mean", np.nan),
            "ic_ir": best.get("ic_ir", np.nan),
            "positive_ic_ratio": best.get("rank_ic_positive_ratio", np.nan),
            "top_bottom_spread": best.get("top_bottom_spread", np.nan),
            "coverage": best.get("coverage_ratio", np.nan),
            "event_count": best.get("sample_count", pd.NA) if is_breakout else pd.NA,
            "win_rate": best.get("rank_ic_positive_ratio", pd.NA),
            "avg_excess_return": best.get("top_bottom_spread", pd.NA),
            "reject_reason": "" if decision != "reject_or_rework" else "role_profile_failed",
            "promote_reason": f"{profile}_pass" if decision == "promote_candidate" else "",
            "watchlist_reason": f"near_pass_under_{profile}" if decision == "watchlist" else "",
        })
    return pd.DataFrame(rows)


def _near_pass(group: pd.DataFrame) -> bool:
    ic_ir = pd.to_numeric(group.get("ic_ir"), errors="coerce").max()
    coverage = pd.to_numeric(group.get("coverage_ratio"), errors="coerce").max()
    positive = pd.to_numeric(group.get("rank_ic_positive_ratio"), errors="coerce").max()
    return bool((pd.notna(ic_ir) and ic_ir >= 0.08) and (pd.notna(coverage) and coverage >= 0.45) and (pd.notna(positive) and positive >= 0.48))


def _final_role_for_factor(factor_name: str, meta: dict, decision: str) -> str:
    if decision == "reject_or_rework":
        return "rejected"
    name = str(factor_name).lower()
    if "overheat" in name:
        return "risk_override"
    if "percentile" in name:
        return "hold_validation"
    return "timing_filter"


def _load_feature_window(feature_path: Path, *, start_date=None, end_date=None, max_days: int | None = None) -> pd.DataFrame:
    import pyarrow.parquet as pq

    available = set(pq.read_schema(feature_path).names)
    columns = [column for column in ["date", "symbol", "close_nominal", "close", "instrument_type"] if column in available]
    filters = []
    effective_start = pd.Timestamp(start_date) if start_date else None
    effective_end = pd.Timestamp(end_date) if end_date else None
    if max_days is not None and effective_end is not None:
        preload_days = int(max_days) * 2 + 450
        limited_start = effective_end - pd.Timedelta(days=preload_days)
        effective_start = max(effective_start, limited_start) if effective_start is not None else limited_start
    if effective_start is not None:
        filters.append(("date", ">=", effective_start))
    if effective_end is not None:
        filters.append(("date", "<=", effective_end))
    data = pd.read_parquet(feature_path, columns=columns, filters=filters or None)
    if max_days is not None and not data.empty:
        dates = sorted(pd.to_datetime(data["date"], errors="coerce").dropna().unique())
        keep_dates = set(dates[-(int(max_days) + 280):])
        data = data[pd.to_datetime(data["date"], errors="coerce").isin(keep_dates)].copy()
    return data


def _old_decision_lookup(summary_path: Path) -> dict[str, str]:
    if not summary_path.exists():
        return {}
    data = pd.read_csv(summary_path, usecols=["factor_name", "verdict"])
    return dict(zip(data["factor_name"].astype(str), data["verdict"].astype(str)))


def _read_manifest(path: Path) -> dict:
    if not path.exists():
        return {}
    data = pd.read_csv(path)
    return data.iloc[0].to_dict() if not data.empty else {}


def _write_split_outputs(appeal: pd.DataFrame, output: Path) -> None:
    appeal[appeal["new_decision"].eq("promote_candidate")].to_csv(output / "admitted_v2.csv", index=False, encoding="utf-8-sig")
    appeal[appeal["new_decision"].eq("watchlist")].to_csv(output / "watchlist_v2.csv", index=False, encoding="utf-8-sig")
    appeal[appeal["new_decision"].eq("reject_or_rework")].to_csv(output / "rejected_v2.csv", index=False, encoding="utf-8-sig")


def _write_distribution_outputs(appeal: pd.DataFrame, output: Path) -> None:
    for column, name in [
        ("new_role", "role_distribution_v2.csv"),
        ("factor_family", "family_distribution_v2.csv"),
        ("judge_profile", "profile_distribution_v2.csv"),
    ]:
        if appeal.empty:
            frame = pd.DataFrame(columns=[column, "count"])
        else:
            frame = appeal.groupby(column, dropna=False).size().reset_index(name="count")
        frame.to_csv(output / name, index=False, encoding="utf-8-sig")


def _write_pending_family_report(target_families: set[str], appeal: pd.DataFrame, output: Path) -> None:
    completed = set(appeal.get("factor_type", pd.Series(dtype=object)).astype(str))
    rows = [{"factor_family": family, "status": "completed" if family in completed else "pending"} for family in sorted(target_families)]
    pd.DataFrame(rows).to_csv(output / "appeal_family_status.csv", index=False, encoding="utf-8-sig")


def _write_manifest(v1_dir: Path, manifest_path: Path, output: Path, run_id: str) -> None:
    pd.DataFrame(
        [
            {
                "appeal_run_id": run_id,
                "appeal_version": "v3_role_aware_rsi_orderflow_breakout",
                "v1_judge_version": "v1_fast_strict",
                "v1_use_as": "first_pass_filter",
                "v1_run_dir": str(v1_dir),
                "v1_manifest": str(manifest_path),
                "v1_overwritten": False,
            }
        ]
    ).to_csv(output / "appeal_manifest.csv", index=False, encoding="utf-8-sig")


def _render_appeal_report(appeal: pd.DataFrame, output: Path) -> str:
    counts = appeal["new_decision"].value_counts().to_dict() if not appeal.empty else {}
    role_counts = appeal["new_role"].value_counts().to_dict() if not appeal.empty else {}
    return "\n".join(
        [
            "# Factor Appeal Judge v2 Report",
            "",
            "Scope: RSI timing, orderflow proxy, and sparse breakout appeals. Fundamental, event, and alternative proxy appeals remain pending.",
            "",
            f"Output directory: `{output}`",
            f"Decision counts: {counts}",
            f"Role counts: {role_counts}",
            "",
            "v1 fast judge outputs were read-only and not overwritten.",
        ]
    )


def _appeal_columns() -> list[str]:
    return [
        "appeal_run_id",
        "v1_run_dir",
        "factor_name",
        "raw_column",
        "direction",
        "parameter_version",
        "factor_family",
        "factor_type",
        "judge_profile",
        "old_decision",
        "new_decision",
        "old_role",
        "new_role",
        "rank_ic",
        "ic_ir",
        "positive_ic_ratio",
        "top_bottom_spread",
        "coverage",
        "event_count",
        "win_rate",
        "avg_excess_return",
        "reject_reason",
        "promote_reason",
        "watchlist_reason",
    ]


def _empty_appeal_summary() -> pd.DataFrame:
    return pd.DataFrame(columns=_appeal_columns())


def merge_appeal_artifacts(
    run_dirs: list[str | Path] | tuple[str | Path, ...],
    *,
    output_root: str | Path = APPEAL_OUTPUT_ROOT,
) -> dict[str, Path]:
    """Combine completed production appeal artifacts without losing provenance."""
    sources = [Path(path) for path in run_dirs if path]
    if len(sources) < 2:
        raise ValueError("At least two appeal artifacts are required for a merge")
    frames: dict[str, list[pd.DataFrame]] = {name: [] for name in ("appeal_summary", "admitted_v2", "watchlist_v2")}
    manifests = []
    for source in sources:
        manifest_path = source / "artifact_manifest.json"
        if not manifest_path.exists():
            raise ValueError(f"Appeal artifact manifest is missing: {source}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if str(manifest.get("status", "")).lower() != "complete" or str(manifest.get("run_kind", "")).lower() != "production":
            raise ValueError(f"Appeal artifact is not completed production output: {source}")
        manifests.append(manifest)
        for name in frames:
            path = source / f"{name}.csv"
            if path.exists():
                frames[name].append(pd.read_csv(path))

    run_id = datetime.now().strftime("run%Y%m%d_%H%M%S_%f")
    output = Path(output_root) / run_id
    output.mkdir(parents=True, exist_ok=False)
    saved: dict[str, Path] = {"output_dir": output}
    for name, parts in frames.items():
        combined = pd.concat(parts, ignore_index=True, sort=False) if parts else _empty_appeal_summary()
        if "factor_name" in combined.columns:
            sort_columns = [column for column in ("research_score", "ic_ir", "rank_ic") if column in combined.columns]
            if sort_columns:
                combined = combined.sort_values(sort_columns, ascending=False, na_position="last")
            combined = combined.drop_duplicates(subset=["factor_name"], keep="first")
        path = output / f"{name}.csv"
        combined.to_csv(path, index=False, encoding="utf-8-sig")
        saved[name] = path
    manifest_path = output / "artifact_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "artifact_type": "factor_appeal_composite",
                "artifact_version": "appeal_composite_v1",
                "run_id": run_id,
                "run_kind": "production",
                "status": "complete",
                "source_run_dirs": [str(path) for path in sources],
                "source_artifacts": manifests,
                "admitted_count": int(len(pd.read_csv(saved["admitted_v2"]))),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    saved["artifact_manifest"] = manifest_path
    return saved
