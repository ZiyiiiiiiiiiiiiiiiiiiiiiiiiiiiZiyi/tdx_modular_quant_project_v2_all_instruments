"""Prune an existing factor cabinet without creating new factors.

The pruner is deliberately read-only with respect to source cabinets. It keeps a
smaller set of existing factor rows and writes a new factor_cabinet run that can
be selected by the normal factor-source resolver.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from functions.decision_council.factor_source import (
    FACTOR_SOURCE_LATEST_CABINET,
    FactorSourceSpec,
    resolve_factor_source,
)


OUTPUT_ROOT = Path("results/factor_cabinet")
REPORT_ROOT = Path("results/factor_cabinet_pruned")

ROLE_TARGETS = {
    "entry_alpha": (6, 25),
    "entry_alpha_proxy": (10, 12),
    "timing_filter": (12, 16),
    "risk_override": (12, 16),
    "liquidity_filter": (10, 12),
    "hold_validation": (10, 12),
}
ROLE_ORDER = {
    "entry_alpha": 0,
    "entry_alpha_proxy": 1,
    "timing_filter": 2,
    "risk_override": 3,
    "hold_validation": 4,
    "liquidity_filter": 5,
}
ROLE_FAMILY_CAP = {
    "entry_alpha": 3,
    "entry_alpha_proxy": 3,
    "timing_filter": 4,
    "risk_override": 4,
    "liquidity_filter": 5,
    "hold_validation": 4,
}
PROTECTED_ECONOMIC_FAMILY_MIN = {
    "orderflow": 1,
    "breakout": 1,
}


def build_factor_cabinet_pruned(
    *,
    factor_source: str = FACTOR_SOURCE_LATEST_CABINET,
    factor_cabinet_run_id: str = "",
    factor_cabinet_path: str = "",
    gap_report_dir: str | Path | None = None,
    corr_threshold: float = 0.98,
    overlap_threshold: float = 0.90,
    output_root: str | Path = OUTPUT_ROOT,
    report_root: str | Path = REPORT_ROOT,
    progress_callback=None,
    require_gap_metrics: bool | None = None,
) -> dict[str, Path]:
    """Write a pruned cabinet run by dropping redundant existing factors."""

    def progress(step: str, percent: float, detail: str = "") -> None:
        if progress_callback is not None:
            progress_callback({"step": step, "percent": float(percent), "detail": detail})
        print(f"[factor_cabinet_pruner] {step}: {detail}", flush=True)

    progress("resolve_factor_cabinet", 5.0)
    spec = resolve_factor_source(
        factor_source=factor_source,
        factor_cabinet_run_id=factor_cabinet_run_id,
        factor_cabinet_path=factor_cabinet_path,
    )
    if not spec.uses_factor_cabinet:
        raise ValueError("factor_cabinet pruner requires latest_factor_cabinet or selected_factor_cabinet")

    source_payload = json.loads(Path(spec.factor_cabinet_path).read_text(encoding="utf-8"))
    if str(source_payload.get("artifact_type") or "").strip() == "factor_cabinet_pruned":
        raise ValueError(
            "factor_cabinet is already pruned; select its unpruned base cabinet before pruning: "
            f"run_id={spec.factor_cabinet_run_id}, "
            f"base_source_run_id={source_payload.get('base_source_run_id') or ''}"
        )
    source_factors = pd.DataFrame(source_payload.get("factors", []))
    if source_factors.empty:
        raise ValueError(f"factor_cabinet has no factors: {spec.factor_cabinet_path}")
    source_factors = _normalize_factor_frame(source_factors)
    progress("load_gap_metrics", 20.0, f"source_factors={len(source_factors)}")
    gap_dir = _resolve_gap_report_dir(spec.factor_cabinet_run_id, gap_report_dir)
    if require_gap_metrics is None:
        require_gap_metrics = (
            str(source_payload.get("generation_policy") or "") == "pit_augmented_v2"
            or str(source_payload.get("artifact_type") or "") == "factor_cabinet_pit_augmented"
        )
    if require_gap_metrics:
        _require_loaded_gap_metrics(gap_dir, spec.factor_cabinet_run_id)
    corr_pairs = _load_pair_metric(gap_dir, "factor_value_spearman_corr.csv", "abs_corr", corr_threshold)
    overlap_pairs = _load_pair_metric(gap_dir, "top_quantile_overlap.csv", "avg_top_overlap", overlap_threshold)
    redundant_pairs = corr_pairs | overlap_pairs

    progress("rank_candidates", 35.0, f"redundant_pairs={len(redundant_pairs)}")
    ranked = _rank_candidates(source_factors)
    protected_augmented_names = _augmented_family_representatives(ranked)
    protected_economic_names = _economic_family_representatives(ranked)
    protected_names = protected_augmented_names | protected_economic_names
    # Reserve protected family representatives inside the normal role caps.
    # Without this ordering, low-frequency breakout/orderflow evidence reaches
    # the loop only after generic factors have already consumed the role quota.
    ranked = pd.concat(
        [
            ranked[ranked["factor_name"].isin(protected_names)],
            ranked[~ranked["factor_name"].isin(protected_names)],
        ],
        ignore_index=True,
    )
    keep_names: set[str] = set()
    decisions: list[dict] = []
    family_counts: dict[tuple[str, str], int] = {}

    for _, row in ranked.iterrows():
        name = str(row["factor_name"])
        role = str(row["role"])
        family = str(row["family"])
        role_min, role_max = ROLE_TARGETS.get(role, (0, 999))
        current_role_count = sum(1 for kept in keep_names if _role_by_name(source_factors, kept) == role)
        family_key = (role, family)
        family_count = int(family_counts.get(family_key, 0))
        family_cap = int(ROLE_FAMILY_CAP.get(role, 4))
        redundant_with = sorted(
            kept for kept in keep_names if frozenset((name, kept)) in redundant_pairs
        )
        reason = "kept"
        keep = True
        if role == "entry_alpha":
            keep = True
            reason = "kept_all_strict_entry_alpha"
        elif name in protected_augmented_names:
            keep = True
            reason = "kept_augmented_family_representative"
        elif name in protected_economic_names:
            keep = True
            reason = "kept_economic_family_representative"
        elif current_role_count >= role_max:
            keep = False
            reason = f"drop_role_cap_{role_max}"
        elif redundant_with and current_role_count >= role_min:
            keep = False
            reason = "drop_redundant_pair"
        elif family_count >= family_cap and current_role_count >= role_min:
            keep = False
            reason = f"drop_family_cap_{family_cap}"

        if keep:
            keep_names.add(name)
            family_counts[family_key] = family_count + 1
        decisions.append(
            {
                "factor_name": name,
                "raw_column": row.get("raw_column", ""),
                "role": role,
                "family": family,
                "module": row.get("module", ""),
                "augmentation_family": row.get("augmentation_family", ""),
                "augmentation_action": row.get("augmentation_action", ""),
                "score": _coerce_float(row.get("score")),
                "best_rank_ic_mean": _coerce_float(row.get("best_rank_ic_mean")),
                "best_ic_ir": _coerce_float(row.get("best_ic_ir")),
                "best_cost_adjusted_top_bottom_spread": _coerce_float(row.get("best_cost_adjusted_top_bottom_spread")),
                "keep": bool(keep),
                "decision_reason": reason,
                "redundant_with_kept": "|".join(redundant_with[:10]),
            }
        )

    progress("write_pruned_cabinet", 75.0, f"kept={len(keep_names)}")
    kept_frame = source_factors[source_factors["factor_name"].isin(keep_names)].copy()
    kept_frame = _rank_candidates(kept_frame)
    base_run_id = _base_source_run_id(source_payload, spec.factor_cabinet_run_id)
    run_id = f"pruned_{base_run_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    cabinet_dir = Path(output_root) / run_id
    report_dir = Path(report_root) / run_id
    cabinet_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    output_payload = {
        "run_id": run_id,
        "source_run_id": spec.factor_cabinet_run_id,
        "base_source_run_id": base_run_id,
        "source_factor_cabinet_path": spec.factor_cabinet_path,
        "artifact_type": "factor_cabinet_pruned",
        "default_eligible": bool(source_payload.get("default_eligible", False)),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "prune_policy": {
            "corr_threshold": float(corr_threshold),
            "overlap_threshold": float(overlap_threshold),
            "role_targets": ROLE_TARGETS,
            "role_family_cap": ROLE_FAMILY_CAP,
            "gap_report_dir": str(gap_dir) if gap_dir else "",
        },
        "factors": _json_records(kept_frame),
    }
    cabinet_path = cabinet_dir / "factor_cabinet.json"
    cabinet_path.write_text(json.dumps(output_payload, ensure_ascii=False, indent=2, allow_nan=True), encoding="utf-8")
    kept_frame.to_csv(cabinet_dir / "factor_cabinet.csv", index=False, encoding="utf-8-sig")

    decisions_frame = pd.DataFrame(decisions)
    summary = _build_summary(
        run_id=run_id,
        source_spec=spec,
        source_factors=source_factors,
        kept_frame=kept_frame,
        decisions=decisions_frame,
        gap_dir=gap_dir,
        corr_pairs=corr_pairs,
        overlap_pairs=overlap_pairs,
    )
    decisions_path = report_dir / "prune_decisions.csv"
    summary_path = report_dir / "prune_summary.json"
    report_path = report_dir / "prune_report.md"
    decisions_frame.to_csv(decisions_path, index=False, encoding="utf-8-sig")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    report_path.write_text(_render_report(summary), encoding="utf-8")
    # Mirror reports into the selectable cabinet directory for easier discovery.
    decisions_frame.to_csv(cabinet_dir / "prune_decisions.csv", index=False, encoding="utf-8-sig")
    summary_path_text = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
    (cabinet_dir / "prune_summary.json").write_text(summary_path_text, encoding="utf-8")
    (cabinet_dir / "prune_report.md").write_text(_render_report(summary), encoding="utf-8")

    progress("complete", 100.0, f"run_id={run_id}, kept={len(kept_frame)}")
    return {
        "factor_cabinet": cabinet_path,
        "factor_cabinet_csv": cabinet_dir / "factor_cabinet.csv",
        "prune_decisions": decisions_path,
        "prune_summary": summary_path,
        "prune_report": report_path,
        "selectable_prune_summary": cabinet_dir / "prune_summary.json",
    }


def _normalize_factor_frame(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    if "role" not in data.columns and "cabinet_role" in data.columns:
        data["role"] = data["cabinet_role"]
    for column in (
        "factor_name", "raw_column", "role", "family", "module",
        "near_relative_key", "source", "augmentation_family", "augmentation_action",
    ):
        if column not in data.columns:
            data[column] = ""
        data[column] = data[column].fillna("").astype(str)
    if "strict_entry_alpha" not in data.columns:
        data["strict_entry_alpha"] = data["role"].eq("entry_alpha")
    data["strict_entry_alpha"] = data["strict_entry_alpha"].fillna(False).astype(bool)
    for column in ("score", "best_rank_ic_mean", "best_ic_ir", "best_cost_adjusted_top_bottom_spread", "avg_turnover_mean"):
        if column not in data.columns:
            data[column] = float("nan")
        data[column] = pd.to_numeric(data[column], errors="coerce")
    return data


def _augmented_family_representatives(ranked: pd.DataFrame) -> set[str]:
    """Keep one evidence-backed addition per economic family through pruning."""
    added = ranked[
        ranked["augmentation_action"].eq("added")
        & ranked["augmentation_family"].ne("")
    ]
    if added.empty:
        return set()
    representatives = added.drop_duplicates("augmentation_family", keep="first")
    return set(representatives["factor_name"].astype(str))


def _economic_family_representatives(ranked: pd.DataFrame) -> set[str]:
    """Protect bounded evidence representatives for required cabinet families."""
    representatives: set[str] = set()
    family_values = ranked["family"].fillna("").astype(str).str.lower()
    for family, minimum in PROTECTED_ECONOMIC_FAMILY_MIN.items():
        family_rows = ranked[family_values.eq(str(family).lower())]
        representatives.update(
            family_rows.head(max(int(minimum), 0))["factor_name"].astype(str).tolist()
        )
    return representatives


def _base_source_run_id(payload: dict, fallback: str) -> str:
    current = str(payload.get("source_run_id") or fallback)
    while current.startswith("pruned_"):
        parts = current.split("_")
        if len(parts) >= 3 and parts[-2].isdigit() and parts[-1].isdigit():
            current = "_".join(parts[1:-2])
        else:
            current = current[len("pruned_"):]
    return current or str(fallback)


def _resolve_gap_report_dir(run_id: str, explicit: str | Path | None) -> Path | None:
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None
    base = Path("results/factor_cabinet_gap_report") / str(run_id)
    if not base.exists():
        return None
    candidates = [
        path for path in base.iterdir()
        if path.is_dir()
        and (path / "factor_value_spearman_corr.csv").exists()
        and (path / "top_quantile_overlap.csv").exists()
    ]
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def _require_loaded_gap_metrics(gap_dir: Path | None, run_id: str) -> None:
    if gap_dir is None:
        raise FileNotFoundError(
            "PIT-augmented cabinet cannot be pruned before its cache-backed gap audit. "
            f"Build the feature cache, then run the gap audit for run_id={run_id}."
        )
    summary_path = gap_dir / "factor_cabinet_gap_summary.json"
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Gap audit summary is missing or invalid: {summary_path}") from exc
    status = str((summary.get("cache_status") or {}).get("status") or "")
    if status != "loaded_sampled":
        raise ValueError(
            "PIT-augmented cabinet gap audit did not load cache metrics; pruning is prohibited. "
            f"run_id={run_id}, cache_status={status or 'missing'}"
        )


def _load_pair_metric(gap_dir: Path | None, filename: str, metric: str, threshold: float) -> set[frozenset[str]]:
    if gap_dir is None:
        return set()
    path = gap_dir / filename
    if not path.exists():
        return set()
    data = pd.read_csv(path, usecols=["factor_a", "factor_b", metric])
    values = pd.to_numeric(data[metric], errors="coerce")
    filtered = data.loc[values.ge(float(threshold)), ["factor_a", "factor_b"]]
    return {
        frozenset((_canonical_factor_name(left), _canonical_factor_name(right)))
        for left, right in filtered.itertuples(index=False)
    }


def _canonical_factor_name(value: str) -> str:
    text = str(value or "")
    if text.startswith("cand_"):
        return "candidate_" + text[len("cand_"):]
    return text


def _rank_candidates(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    data["_role_order"] = data["role"].map(ROLE_ORDER).fillna(99).astype(int)
    data["_score_rank"] = pd.to_numeric(data["score"], errors="coerce").fillna(-999.0)
    data["_ic_ir_rank"] = pd.to_numeric(data["best_ic_ir"], errors="coerce").fillna(-999.0)
    data["_spread_rank"] = pd.to_numeric(data["best_cost_adjusted_top_bottom_spread"], errors="coerce").fillna(-999.0)
    data["_strict_rank"] = data["strict_entry_alpha"].fillna(False).astype(bool).astype(int)
    return data.sort_values(
        ["_role_order", "_strict_rank", "_score_rank", "_ic_ir_rank", "_spread_rank", "factor_name"],
        ascending=[True, False, False, False, False, True],
    ).drop(columns=["_role_order", "_score_rank", "_ic_ir_rank", "_spread_rank", "_strict_rank"], errors="ignore")


def _role_by_name(frame: pd.DataFrame, factor_name: str) -> str:
    matched = frame.loc[frame["factor_name"].eq(str(factor_name)), "role"]
    return str(matched.iloc[0]) if not matched.empty else ""


def _build_summary(
    *,
    run_id: str,
    source_spec: FactorSourceSpec,
    source_factors: pd.DataFrame,
    kept_frame: pd.DataFrame,
    decisions: pd.DataFrame,
    gap_dir: Path | None,
    corr_pairs: set[frozenset[str]],
    overlap_pairs: set[frozenset[str]],
) -> dict:
    role_distribution = {str(k): int(v) for k, v in kept_frame["role"].value_counts().sort_index().items()}
    source_role_distribution = {str(k): int(v) for k, v in source_factors["role"].value_counts().sort_index().items()}
    drop_reasons = {str(k): int(v) for k, v in decisions.loc[~decisions["keep"], "decision_reason"].value_counts().items()}
    family = (
        kept_frame.groupby(["role", "family"], dropna=False)
        .size()
        .reset_index(name="factor_count")
        .sort_values("factor_count", ascending=False)
    )
    return {
        "artifact_type": "factor_cabinet_pruned",
        "run_id": run_id,
        "source_run_id": source_spec.factor_cabinet_run_id,
        "source_factor_cabinet_path": source_spec.factor_cabinet_path,
        "gap_report_dir": str(gap_dir) if gap_dir else "",
        "source_factor_count": int(len(source_factors)),
        "kept_factor_count": int(len(kept_frame)),
        "dropped_factor_count": int(len(source_factors) - len(kept_frame)),
        "source_role_distribution": source_role_distribution,
        "role_distribution": role_distribution,
        "drop_reasons": drop_reasons,
        "redundant_corr_pairs_loaded": int(len(corr_pairs)),
        "redundant_overlap_pairs_loaded": int(len(overlap_pairs)),
        "max_family_count_after_prune": int(family["factor_count"].max()) if not family.empty else 0,
        "entry_alpha_count": int(role_distribution.get("entry_alpha", 0)),
        "entry_alpha_proxy_count": int(role_distribution.get("entry_alpha_proxy", 0)),
        "liquidity_filter_count": int(role_distribution.get("liquidity_filter", 0)),
        "augmented_family_representatives": sorted(
            decisions.loc[
                decisions["decision_reason"].eq("kept_augmented_family_representative"),
                "factor_name",
            ].astype(str).tolist()
        ),
        "economic_family_representatives": sorted(
            decisions.loc[
                decisions["decision_reason"].eq("kept_economic_family_representative"),
                "factor_name",
            ].astype(str).tolist()
        ),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "invariants": {
            "no_new_factors": bool(set(kept_frame["factor_name"]) <= set(source_factors["factor_name"])),
            "source_not_modified": True,
            "strict_entry_alpha_preserved": int(role_distribution.get("entry_alpha", 0)) == int(source_role_distribution.get("entry_alpha", 0)),
            "protected_economic_families_preserved": all(
                int((kept_frame["family"].str.lower() == family).sum()) >= minimum
                for family, minimum in PROTECTED_ECONOMIC_FAMILY_MIN.items()
                if int((source_factors["family"].str.lower() == family).sum()) >= minimum
            ),
        },
    }


def _render_report(summary: dict) -> str:
    lines = [
        "# Factor Cabinet Prune Report",
        "",
        f"- run_id: {summary['run_id']}",
        f"- source_run_id: {summary['source_run_id']}",
        f"- source factors: {summary['source_factor_count']}",
        f"- kept factors: {summary['kept_factor_count']}",
        f"- dropped factors: {summary['dropped_factor_count']}",
        f"- role distribution: {summary['role_distribution']}",
        f"- drop reasons: {summary['drop_reasons']}",
        f"- redundant corr pairs loaded: {summary['redundant_corr_pairs_loaded']}",
        f"- redundant overlap pairs loaded: {summary['redundant_overlap_pairs_loaded']}",
        "",
        "## Invariants",
        "",
    ]
    for key, value in summary.get("invariants", {}).items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines) + "\n"


def _json_records(frame: pd.DataFrame) -> list[dict]:
    records = []
    for record in frame.to_dict("records"):
        records.append({str(key): _json_value(value) for key, value in record.items()})
    return records


def _json_value(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _coerce_float(value, default=None):
    try:
        numeric = float(value)
    except Exception:
        return default
    if pd.isna(numeric):
        return default
    return numeric
