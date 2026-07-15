"""Build the final factor cabinet consumed by the state machine."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json

import pandas as pd

from functions.decision_council.factor_source import is_factor_cabinet_runtime_column


DEFAULT_V1_CONTRACT = Path(
    "results/decision_council/fast_factor_judge/"
    "hs300_csi500_a500_strict/run20260705_180001_095951/factor_pool_contract.csv"
)
DEFAULT_APPEAL_ROOT = Path("results/decision_council/factor_appeal_judge")
OUTPUT_ROOT = Path("results/factor_cabinet")
ROLE_QUOTA = {
    "strict_entry_alpha": (6, 40),
    "proxy_entry_alpha": (20, 40),
    "timing_filter": (15, 25),
    "risk_override": (15, 25),
    "liquidity_filter": (10, 20),
    "hold_validation": (10, 20),
}
PIT_AUGMENT_FAMILY_CAP = {
    "valuation": 3,
    "profitability": 4,
    "investment": 3,
    "cashflow": 4,
    "growth": 5,
    "event": 5,
    "rsi": 4,
    "orderflow": 4,
    "breakout": 2,
}
PIT_AUGMENT_ROLE_CAP = {
    "proxy_entry_alpha": 10,
    "timing_filter": 6,
    "risk_override": 6,
    "liquidity_filter": 4,
    "hold_validation": 6,
}
PIT_AUGMENT_TARGET_FAMILIES = tuple(PIT_AUGMENT_FAMILY_CAP)


def build_factor_cabinet(
    *,
    v1_contract_path: str | Path = DEFAULT_V1_CONTRACT,
    appeal_run_dir: str | Path | None = None,
    output_root: str | Path = OUTPUT_ROOT,
    min_factors: int = 60,
    max_factors: int = 120,
    base_cabinet_path: str | Path | None = None,
    augmented_max_factors: int = 150,
) -> dict[str, Path]:
    v2 = _load_v2(appeal_run_dir)
    appeal_provenance = _appeal_provenance(v2)
    base_path = Path(base_cabinet_path).resolve() if base_cabinet_path else None
    base_artifact_type = ""
    base_lineage_status = "not_applicable"
    base_lineage_warning = ""
    available_pruned_candidate_run_id = ""
    available_pruned_candidate_path = ""
    if base_path is not None:
        base_payload = _read_cabinet_payload(base_path)
        base_artifact_type = str(base_payload.get("artifact_type") or "factor_cabinet").strip()
        pruned_descendant = find_latest_pruned_descendant(base_path, search_root=output_root)
        if pruned_descendant is not None:
            descendant_run_id, descendant_path = pruned_descendant
            raise ValueError(
                "Selected base factor cabinet already has a pruned descendant; "
                "refusing to rebuild from the unpruned ancestor. "
                f"selected_run_id={base_payload.get('run_id') or base_path.parent.name}, "
                f"recommended_run_id={descendant_run_id}, recommended_path={descendant_path}"
            )
        base_lineage_status = (
            "pruned_base"
            if base_artifact_type == "factor_cabinet_pruned"
            else "unpruned_base_requires_downstream_prune"
        )
        if base_lineage_status != "pruned_base":
            base_lineage_warning = (
                "The selected base cabinet is not pruned. The augmented cabinet must complete "
                "a cache-backed gap audit and pruning before production promotion."
            )
            unrelated_pruned = find_latest_pruned_cabinet(search_root=output_root)
            if unrelated_pruned is not None:
                available_pruned_candidate_run_id, unrelated_path = unrelated_pruned
                available_pruned_candidate_path = str(unrelated_path)
                base_lineage_warning += (
                    " A pruned cabinet exists but is not a verified descendant of the selected base, "
                    "so it was not substituted automatically: "
                    f"run_id={available_pruned_candidate_run_id}."
                )
            print(f"[factor_cabinet_builder] lineage_warning: {base_lineage_warning}", flush=True)
        base, base_run_id = _load_base_cabinet(base_path)
        selected, dedup_report, quota_report, family_report = _build_pit_augmented_cabinet(
            base,
            v2,
            augmented_max_factors=int(augmented_max_factors),
        )
        generation_policy = "pit_augmented_v2"
    else:
        v1 = _load_v1(v1_contract_path)
        candidates = pd.concat([v1, v2], ignore_index=True)
        if candidates.empty:
            raise ValueError("No cabinet candidates available")
        candidates["cabinet_score"] = candidates.apply(_cabinet_score, axis=1)
        deduped, dedup_report = _near_relative_dedup(candidates)
        deduped = _assign_proxy_entry_roles(deduped)
        selected, quota_report = _select_by_role(deduped, min_factors=min_factors, max_factors=max_factors)
        family_report = pd.DataFrame()
        base_run_id = ""
        generation_policy = "judge_pool_rebuild_v1"
    _validate_runtime_contract(selected)
    run_id = datetime.now().strftime("run%Y%m%d_%H%M%S_%f")
    output = Path(output_root) / run_id
    output.mkdir(parents=True, exist_ok=False)
    selected.to_csv(output / "factor_cabinet.csv", index=False, encoding="utf-8-sig")
    payload = {
        "run_id": run_id,
        "artifact_type": "factor_cabinet_pit_augmented" if base_path is not None else "factor_cabinet",
        "generation_policy": generation_policy,
        "base_source_run_id": base_run_id,
        "base_factor_cabinet_path": str(base_path) if base_path is not None else "",
        "base_artifact_type": base_artifact_type,
        "base_lineage_status": base_lineage_status,
        "base_lineage_warning": base_lineage_warning,
        "available_pruned_candidate_run_id": available_pruned_candidate_run_id,
        "available_pruned_candidate_path": available_pruned_candidate_path,
        "base_factor_count": int(len(base)) if base_path is not None else 0,
        "added_factor_count": int(selected.get("augmentation_action", pd.Series(dtype=str)).eq("added").sum()),
        "appeal_source_run_id": appeal_provenance["run_id"],
        "appeal_source_path": appeal_provenance["path"],
        "appeal_artifact_types": appeal_provenance["artifact_types"],
        "appeal_artifact_versions": appeal_provenance["artifact_versions"],
        "pit_level2_appeal_evaluated": appeal_provenance["pit_level2_evaluated"],
        "orderflow_parameter_research_evaluated": appeal_provenance["orderflow_research_evaluated"],
        "default_eligible": bool(
            base_path is not None
            and appeal_provenance["pit_level2_evaluated"]
            and appeal_provenance["orderflow_research_evaluated"]
        ),
        "factors": selected.to_dict("records"),
    }
    (output / "factor_cabinet.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    dedup_report.to_csv(output / "near_relative_dedup_report.csv", index=False, encoding="utf-8-sig")
    _correlation_cluster_placeholder(selected).to_csv(output / "correlation_cluster_report.csv", index=False, encoding="utf-8-sig")
    quota_report.to_csv(output / "role_quota_report.csv", index=False, encoding="utf-8-sig")
    family_report.to_csv(output / "pit_family_inclusion_report.csv", index=False, encoding="utf-8-sig")
    if base_path is not None:
        _base_preservation_report(base, selected).to_csv(
            output / "base_cabinet_preservation_report.csv", index=False, encoding="utf-8-sig"
        )
    else:
        pd.DataFrame(columns=["factor_name", "raw_column", "preserved"]).to_csv(
            output / "base_cabinet_preservation_report.csv", index=False, encoding="utf-8-sig"
        )
    (output / "factor_cabinet_report.md").write_text(
        _render_report(
            selected,
            quota_report,
            generation_policy=generation_policy,
            base_run_id=base_run_id,
            base_factor_count=int(len(base)) if base_path is not None else 0,
            family_report=family_report,
            appeal_provenance=appeal_provenance,
            default_eligible=bool(payload["default_eligible"]),
        ),
        encoding="utf-8",
    )
    return {
        "output_dir": output,
        "factor_cabinet": output / "factor_cabinet.json",
        "factor_cabinet_json": output / "factor_cabinet.json",
        "factor_cabinet_csv": output / "factor_cabinet.csv",
        "factor_cabinet_report": output / "factor_cabinet_report.md",
        "near_relative_dedup_report": output / "near_relative_dedup_report.csv",
        "correlation_cluster_report": output / "correlation_cluster_report.csv",
        "role_quota_report": output / "role_quota_report.csv",
        "pit_family_inclusion_report": output / "pit_family_inclusion_report.csv",
        "base_cabinet_preservation_report": output / "base_cabinet_preservation_report.csv",
    }


def _load_base_cabinet(path: Path) -> tuple[pd.DataFrame, str]:
    if not path.exists():
        raise FileNotFoundError(f"Base factor cabinet not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    data = pd.DataFrame(payload.get("factors", []))
    if data.empty:
        raise ValueError(f"Base factor cabinet has no factors: {path}")
    required = {"factor_name", "raw_column", "role", "module", "family"}
    missing = sorted(required - set(data.columns))
    if missing:
        raise ValueError(f"Base factor cabinet missing columns: {missing}")
    data = data.copy()
    data["source"] = data.get("source", "base_cabinet")
    data["decision"] = "base_preserved"
    data["augmentation_action"] = "preserved"
    score_values = data.get(
        "cabinet_score",
        data.get("score", pd.Series(0.0, index=data.index, dtype=float)),
    )
    data["cabinet_score"] = pd.to_numeric(score_values, errors="coerce").fillna(0.0)
    strict = data.get("strict_entry_alpha", pd.Series(False, index=data.index)).fillna(False).astype(bool)
    role = data["role"].fillna("").astype(str)
    data["cabinet_role"] = role
    data.loc[role.eq("entry_alpha") & strict, "cabinet_role"] = "strict_entry_alpha"
    data.loc[role.eq("entry_alpha") & ~strict, "cabinet_role"] = "proxy_entry_alpha"
    data.loc[role.eq("entry_alpha_proxy"), "cabinet_role"] = "proxy_entry_alpha"
    if "near_relative_key" not in data.columns:
        data["near_relative_key"] = (
            data["module"].astype(str) + ":" + data["family"].astype(str) + ":" + data["factor_name"].astype(str)
        )
    return data, str(payload.get("run_id") or path.parent.name)


def _read_cabinet_payload(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Factor cabinet not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Factor cabinet payload must be an object: {path}")
    return payload


def find_latest_pruned_descendant(
    base_cabinet_path: str | Path,
    *,
    search_root: str | Path = OUTPUT_ROOT,
) -> tuple[str, Path] | None:
    """Return the newest transitive pruned child of a selected cabinet."""
    base_path = Path(base_cabinet_path).resolve()
    base_payload = _read_cabinet_payload(base_path)
    if str(base_payload.get("artifact_type") or "").strip() == "factor_cabinet_pruned":
        return None
    base_run_id = str(base_payload.get("run_id") or base_path.parent.name).strip()
    root = Path(search_root)
    if not root.exists():
        return None

    candidates: list[tuple[str, Path, dict]] = []
    for run_dir in root.iterdir():
        candidate_path = run_dir / "factor_cabinet.json"
        if not run_dir.is_dir() or not candidate_path.exists():
            continue
        try:
            payload = _read_cabinet_payload(candidate_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        candidates.append((str(payload.get("run_id") or run_dir.name), candidate_path.resolve(), payload))

    lineage = {base_run_id}
    descendants: list[tuple[str, Path]] = []
    changed = True
    while changed:
        changed = False
        for run_id, candidate_path, payload in candidates:
            if run_id in lineage:
                continue
            source_run_id = str(payload.get("source_run_id") or "").strip()
            if source_run_id not in lineage:
                continue
            lineage.add(run_id)
            changed = True
            if str(payload.get("artifact_type") or "").strip() == "factor_cabinet_pruned":
                descendants.append((run_id, candidate_path))
    if not descendants:
        return None
    return max(descendants, key=lambda item: item[1].stat().st_mtime)


def find_latest_pruned_cabinet(
    *,
    search_root: str | Path = OUTPUT_ROOT,
) -> tuple[str, Path] | None:
    """Return the newest pruned artifact without implying lineage compatibility."""
    root = Path(search_root)
    if not root.exists():
        return None
    candidates: list[tuple[str, Path]] = []
    for run_dir in root.iterdir():
        candidate_path = run_dir / "factor_cabinet.json"
        if not run_dir.is_dir() or not candidate_path.exists():
            continue
        try:
            payload = _read_cabinet_payload(candidate_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if str(payload.get("artifact_type") or "").strip() != "factor_cabinet_pruned":
            continue
        candidates.append((str(payload.get("run_id") or run_dir.name), candidate_path.resolve()))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[1].stat().st_mtime)


def _build_pit_augmented_cabinet(
    base: pd.DataFrame,
    appeals: pd.DataFrame,
    *,
    augmented_max_factors: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if augmented_max_factors < len(base):
        raise ValueError(
            f"augmented_max_factors={augmented_max_factors} is below base factor count={len(base)}"
        )
    candidates = appeals.copy()
    if candidates.empty:
        candidates = pd.DataFrame(columns=base.columns)
    candidates = candidates[
        candidates.get("decision", pd.Series("", index=candidates.index)).astype(str).eq("promote_candidate")
    ].copy()
    candidates["cabinet_score"] = candidates.apply(_cabinet_score, axis=1) if not candidates.empty else pd.Series(dtype=float)
    candidates["augmentation_action"] = "added"
    factor_type = candidates.get("factor_type", pd.Series("", index=candidates.index)).fillna("").astype(str)
    family_value = candidates.get("family", pd.Series("", index=candidates.index)).fillna("").astype(str)
    candidates["augmentation_family"] = factor_type.where(
        factor_type.isin(PIT_AUGMENT_TARGET_FAMILIES), family_value
    )
    base_names = set(base["factor_name"].astype(str))
    base_raw = set(base["raw_column"].astype(str))
    duplicate_mask = (
        candidates["factor_name"].astype(str).isin(base_names)
        | candidates["raw_column"].astype(str).isin(base_raw)
    ) if not candidates.empty else pd.Series(dtype=bool)
    duplicate_rows = candidates[duplicate_mask].copy() if not candidates.empty else pd.DataFrame()
    candidates = candidates[~duplicate_mask].copy() if not candidates.empty else candidates
    deduped, near_report = _near_relative_dedup(candidates) if not candidates.empty else (candidates, pd.DataFrame())
    decisions = []
    selected_additions = []
    family_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    room = max(int(augmented_max_factors) - len(base), 0)
    for _, row in deduped.sort_values(["cabinet_score", "factor_name"], ascending=[False, True]).iterrows():
        family = str(row.get("augmentation_family", row.get("family", "")))
        role = str(row.get("cabinet_role", ""))
        family_cap = int(PIT_AUGMENT_FAMILY_CAP.get(family, 2))
        role_cap = int(PIT_AUGMENT_ROLE_CAP.get(role, 2))
        keep = True
        reason = "added_promoted_factor"
        if len(selected_additions) >= room:
            keep, reason = False, "augmented_total_cap"
        elif family_counts.get(family, 0) >= family_cap:
            keep, reason = False, f"new_family_cap_{family_cap}"
        elif role_counts.get(role, 0) >= role_cap:
            keep, reason = False, f"new_role_cap_{role_cap}"
        if keep:
            selected_additions.append(row)
            family_counts[family] = family_counts.get(family, 0) + 1
            role_counts[role] = role_counts.get(role, 0) + 1
        decisions.append({
            "factor_name": row.get("factor_name", ""), "family": family,
            "role": row.get("role", ""), "selected": keep, "reason": reason,
        })
    additions = pd.DataFrame(selected_additions)
    selected = pd.concat([base, additions], ignore_index=True, sort=False).drop_duplicates("factor_name", keep="first")
    if len(selected) < len(base):
        raise AssertionError("PIT augmentation unexpectedly removed base factors")
    dedup_report = pd.concat([
        near_report,
        duplicate_rows.assign(action="drop", reason="already_present_in_base")[
            [column for column in ("near_relative_key", "factor_name", "action", "reason") if column in duplicate_rows.columns or column in {"action", "reason"}]
        ] if not duplicate_rows.empty else pd.DataFrame(),
    ], ignore_index=True, sort=False)
    quota_report = pd.DataFrame([
        {"scope": "augmentation", "role": role, "target_min": 0, "target_max": cap,
         "selected": role_counts.get(role, 0), "pass": role_counts.get(role, 0) <= cap}
        for role, cap in PIT_AUGMENT_ROLE_CAP.items()
    ])
    family_rows = []
    decision_frame = pd.DataFrame(decisions)
    for family in PIT_AUGMENT_TARGET_FAMILIES:
        promoted = int((candidates.get("augmentation_family", pd.Series(dtype=str)).astype(str) == family).sum())
        selected_count = int(family_counts.get(family, 0))
        family_rows.append({
            "family": family, "promoted_available": promoted,
            "selected_additions": selected_count,
            "status": "included" if selected_count else ("no_promoted_evidence" if promoted == 0 else "blocked_by_caps"),
            "forced_inclusion": False,
        })
    return selected.reset_index(drop=True), dedup_report, quota_report, pd.DataFrame(family_rows)


def _base_preservation_report(base: pd.DataFrame, selected: pd.DataFrame) -> pd.DataFrame:
    selected_names = set(selected["factor_name"].astype(str))
    return pd.DataFrame({
        "factor_name": base["factor_name"].astype(str),
        "raw_column": base["raw_column"].astype(str),
        "preserved": base["factor_name"].astype(str).isin(selected_names),
    })


def _load_v1(path: str | Path) -> pd.DataFrame:
    data = pd.read_csv(path)
    data = data[data.get("admitted", False).astype(str).str.lower().eq("true")].copy()
    if data.empty:
        return pd.DataFrame()
    data["source"] = "v1_fast_strict"
    data["decision"] = data["verdict"]
    data["cabinet_role"] = data.apply(_cabinet_role_from_v1, axis=1)
    data["strict_entry_alpha"] = data["cabinet_role"].eq("strict_entry_alpha")
    return data


def _load_v2(appeal_run_dir: str | Path | None) -> pd.DataFrame:
    run_dir = _resolve_appeal_run_dir(appeal_run_dir)
    if run_dir is None:
        return pd.DataFrame()
    manifest_path = run_dir / "artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    parts = []
    for filename in ("admitted_v2.csv", "watchlist_v2.csv"):
        path = run_dir / filename
        if path.exists():
            parts.append(pd.read_csv(path))
    parts = [part for part in parts if part is not None and not part.empty]
    if not parts:
        empty = pd.DataFrame()
        empty.attrs.update({"appeal_run_dir": str(run_dir), "appeal_manifest": manifest})
        return empty
    data = pd.concat(parts, ignore_index=True)
    data["source"] = "v2_appeal"
    data["decision"] = data["new_decision"]
    data["module"] = data.get("factor_type", "")
    data["family"] = data.get("factor_family", "")
    data["role"] = data["new_role"].map(
        lambda role: "entry_alpha_proxy" if str(role) in {"entry_alpha", "entry_alpha_proxy"} else str(role)
    )
    data["cabinet_role"] = data["new_role"].map(
        lambda role: "proxy_entry_alpha" if str(role) in {"entry_alpha", "entry_alpha_proxy"} else str(role)
    )
    data["near_relative_key"] = data["factor_type"].astype(str) + ":" + data["factor_family"].astype(str) + ":" + data["factor_name"].astype(str)
    data["score"] = pd.to_numeric(data.get("ic_ir"), errors="coerce").fillna(0.0)
    data["strict_entry_alpha"] = False
    # v3 RSI appeal artifacts predate the cand_* runtime-column contract.
    # This is the only legacy mapping accepted here; unknown columns fail below.
    legacy_rsi = (
        data["factor_type"].astype(str).eq("rsi")
        & ~data["raw_column"].map(is_factor_cabinet_runtime_column)
    )
    data.loc[legacy_rsi, "raw_column"] = "cand_" + data.loc[legacy_rsi, "factor_name"].astype(str)
    data.attrs.update({"appeal_run_dir": str(run_dir), "appeal_manifest": manifest})
    return data


def _validate_runtime_contract(frame: pd.DataFrame) -> None:
    required = {"factor_name", "raw_column", "role"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"factor_cabinet output is missing runtime columns: {missing}")
    names = frame["factor_name"].fillna("").astype(str).str.strip()
    raw_columns = frame["raw_column"].fillna("").astype(str).str.strip()
    roles = frame["role"].fillna("").astype(str).str.strip()
    invalid = frame.loc[
        names.eq("")
        | raw_columns.eq("")
        | ~raw_columns.map(is_factor_cabinet_runtime_column)
        | ~roles.isin({
            "entry_alpha", "entry_alpha_proxy", "timing_filter", "risk_override",
            "liquidity_filter", "hold_validation", "sell_trigger",
        })
    ]
    if not invalid.empty:
        columns = [column for column in ("factor_name", "raw_column", "role", "module", "family") if column in invalid]
        raise ValueError(
            "factor_cabinet builder produced invalid runtime metadata: "
            f"{invalid[columns].head(10).to_dict('records')}"
        )
    duplicates = sorted(names[names.duplicated(keep=False)].unique())
    if duplicates:
        raise ValueError(f"factor_cabinet builder produced duplicate factor names: {duplicates[:10]}")


def _appeal_provenance(data: pd.DataFrame) -> dict:
    manifest = dict(data.attrs.get("appeal_manifest") or {})
    artifact_types: set[str] = set()
    artifact_versions: set[str] = set()

    def collect(item) -> None:
        if not isinstance(item, dict):
            return
        artifact_type = str(item.get("artifact_type") or "").strip()
        artifact_version = str(item.get("artifact_version") or "").strip()
        if artifact_type:
            artifact_types.add(artifact_type)
        if artifact_version:
            artifact_versions.add(artifact_version)
        for child in item.get("source_artifacts", []) or []:
            collect(child)

    collect(manifest)
    return {
        "run_id": str(manifest.get("run_id") or ""),
        "path": str(data.attrs.get("appeal_run_dir") or ""),
        "artifact_types": sorted(artifact_types),
        "artifact_versions": sorted(artifact_versions),
        "pit_level2_evaluated": any("pit_level2" in value for value in artifact_versions),
        "orderflow_research_evaluated": "orderflow_parameter_research" in artifact_types,
    }


def _resolve_appeal_run_dir(appeal_run_dir: str | Path | None) -> Path | None:
    if appeal_run_dir:
        run_dir = Path(appeal_run_dir)
        if not _is_consumable_appeal_run(run_dir, allow_legacy=True):
            raise ValueError(f"Appeal run is incomplete or not consumable: {run_dir}")
        return run_dir
    if not DEFAULT_APPEAL_ROOT.exists():
        return None
    candidates = sorted(
        (path for path in DEFAULT_APPEAL_ROOT.iterdir() if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for run_dir in candidates:
        if _is_consumable_appeal_run(run_dir, allow_legacy=True):
            return run_dir
    return None


def _is_consumable_appeal_run(run_dir: Path, *, allow_legacy: bool) -> bool:
    manifest_path = run_dir / "artifact_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if str(manifest.get("status", "")).lower() != "complete":
            return False
        if str(manifest.get("run_kind", "production")).lower() != "production":
            return False
        return (run_dir / "appeal_summary.csv").exists() and (run_dir / "admitted_v2.csv").exists()
    if not allow_legacy:
        return False
    # Backward compatibility is intentionally strict: test artifacts whose
    # admitted output was renamed must never become the implicit production run.
    return (
        (run_dir / "appeal_manifest.csv").exists()
        and (run_dir / "appeal_summary.csv").exists()
        and (run_dir / "admitted_v2.csv").exists()
    )


def _cabinet_role_from_v1(row) -> str:
    role = str(row.get("role", ""))
    module = str(row.get("module", "")).lower()
    family = str(row.get("family", "")).lower()
    if role == "entry_alpha":
        if any(token in module + family for token in ("trend", "breakout", "orderflow", "quality", "value", "event", "relative_strength")):
            return "proxy_entry_alpha"
        return "strict_entry_alpha"
    return role


def _cabinet_score(row) -> float:
    # Judge outputs are already normalized to the declared economic direction.
    # Negative evidence must not be revived by taking an absolute value.
    rank_ic = max(_num(row.get("best_rank_ic_mean", row.get("rank_ic")), 0.0), 0.0)
    ic_ir = max(_num(row.get("best_ic_ir", row.get("ic_ir")), 0.0), 0.0)
    spread = _num(
        row.get("best_cost_adjusted_top_bottom_spread", row.get("top_bottom_spread")),
        0.0,
    )
    turnover = _num(row.get("avg_turnover_mean", row.get("avg_turnover")), 0.5)
    coverage = _num(row.get("coverage"), 1.0)
    stability = _num(row.get("positive_ic_ratio"), 0.52)
    turnover_score = max(1.0 - turnover, 0.0)
    return 0.30 * rank_ic + 0.25 * ic_ir + 0.20 * max(spread, 0.0) + 0.10 * stability + 0.10 * turnover_score + 0.05 * coverage


def _num(value, default: float = 0.0) -> float:
    value = pd.to_numeric(value, errors="coerce")
    if pd.isna(value):
        return float(default)
    return float(value)


def _assign_proxy_entry_roles(candidates: pd.DataFrame) -> pd.DataFrame:
    data = candidates.copy()
    if data.empty:
        return data
    text = (
        data.get("module", pd.Series("", index=data.index)).astype(str).str.lower()
        + "|"
        + data.get("family", pd.Series("", index=data.index)).astype(str).str.lower()
        + "|"
        + data.get("factor_name", pd.Series("", index=data.index)).astype(str).str.lower()
    )
    proxy_tokens = (
        "trend",
        "breakout",
        "turtle",
        "macd",
        "rsi",
        "large_order",
        "orderflow",
        "volume_price",
        "amount_shock",
        "value_proxy",
        "barra",
        "quality",
        "efficiency",
    )
    role = data.get("cabinet_role", pd.Series("", index=data.index)).astype(str)
    eligible = role.isin(["timing_filter", "hold_validation", "liquidity_filter"]) & text.apply(
        lambda item: any(token in item for token in proxy_tokens)
    )
    current_proxy_count = int(role.eq("proxy_entry_alpha").sum())
    needed = max(ROLE_QUOTA["proxy_entry_alpha"][0] - current_proxy_count, 0)
    if needed <= 0:
        return data
    selected_index = data.loc[eligible].sort_values("cabinet_score", ascending=False).head(needed).index
    data.loc[selected_index, "cabinet_role"] = "proxy_entry_alpha"
    data.loc[selected_index, "role"] = "entry_alpha_proxy"
    data.loc[selected_index, "proxy_entry_reason"] = "admitted_non_entry_alpha_used_for_basket_entry_proxy"
    return data


def _near_relative_dedup(candidates: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    kept = []
    for key, group in candidates.sort_values(["cabinet_score", "factor_name"], ascending=[False, True]).groupby("near_relative_key", dropna=False):
        limit = 2 if _cross_regime_stable(group) else 1
        keep = group.head(limit)
        drop = group.iloc[limit:]
        kept.append(keep)
        for _, row in keep.iterrows():
            rows.append({"near_relative_key": key, "factor_name": row["factor_name"], "action": "keep", "reason": f"top_{limit}_by_cabinet_score"})
        for _, row in drop.iterrows():
            rows.append({"near_relative_key": key, "factor_name": row["factor_name"], "action": "drop", "reason": "near_relative_limit"})
    return pd.concat(kept, ignore_index=True) if kept else pd.DataFrame(), pd.DataFrame(rows)


def _cross_regime_stable(group: pd.DataFrame) -> bool:
    return bool(pd.to_numeric(group.get("positive_ic_ratio", 0.0), errors="coerce").fillna(0.0).max() >= 0.58)


def _select_by_role(candidates: pd.DataFrame, *, min_factors: int, max_factors: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    selected_parts = []
    quota_rows = []
    used = set()
    for role, (min_count, max_count) in ROLE_QUOTA.items():
        group = candidates[candidates["cabinet_role"].astype(str).eq(role)].sort_values("cabinet_score", ascending=False)
        take = group.head(max_count).copy()
        selected_parts.append(take)
        used.update(take["factor_name"].astype(str))
        quota_rows.append({"role": role, "target_min": min_count, "target_max": max_count, "selected": int(len(take)), "pass": bool(len(take) >= min_count)})
    selected = pd.concat(selected_parts, ignore_index=True) if selected_parts else pd.DataFrame()
    protected = candidates[
        candidates.get("source", pd.Series("", index=candidates.index)).astype(str).eq("v2_appeal")
        & candidates.get("decision", pd.Series("", index=candidates.index)).astype(str).eq("promote_candidate")
        & candidates.get("factor_type", pd.Series("", index=candidates.index)).astype(str).isin({
            "breakout", "orderflow_proxy", "rsi", "growth", "profitability",
            "cashflow", "valuation", "investment", "event",
        })
    ].copy()
    if not protected.empty:
        selected = pd.concat(
            [selected[~selected["factor_name"].astype(str).isin(protected["factor_name"].astype(str))], protected],
            ignore_index=True,
        )
        protected_names = set(protected["factor_name"].astype(str))
        trimmed = []
        for role, (_, role_max) in ROLE_QUOTA.items():
            group = selected[selected["cabinet_role"].astype(str).eq(role)].copy()
            group["_protected"] = group["factor_name"].astype(str).isin(protected_names)
            group = group.sort_values(["_protected", "cabinet_score"], ascending=[False, False]).head(role_max)
            trimmed.append(group.drop(columns="_protected"))
        selected = pd.concat(trimmed, ignore_index=True) if trimmed else selected
    selected = selected.drop_duplicates("factor_name", keep="first")
    used = set(selected["factor_name"].astype(str))
    if len(selected) < min_factors:
        extra = candidates[~candidates["factor_name"].astype(str).isin(used)].sort_values("cabinet_score", ascending=False).head(min_factors - len(selected))
        selected = pd.concat([selected, extra], ignore_index=True)
    selected = selected.sort_values(["cabinet_role", "cabinet_score"], ascending=[True, False]).head(max_factors).reset_index(drop=True)
    return selected, pd.DataFrame(quota_rows)


def _correlation_cluster_placeholder(selected: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for cluster_id, (_, group) in enumerate(selected.groupby("family", dropna=False), start=1):
        for _, row in group.iterrows():
            rows.append({
                "cluster_id": cluster_id,
                "factor_name": row["factor_name"],
                "family": row.get("family", ""),
                "cluster_size": int(len(group)),
                "reason": "metadata_family_group_not_value_correlation",
            })
    return pd.DataFrame(rows)


def _latest_dir(root: Path) -> Path | None:
    if not root.exists():
        return None
    dirs = [path for path in root.iterdir() if path.is_dir() and path.name.startswith("run")]
    return sorted(dirs, key=lambda path: path.stat().st_mtime, reverse=True)[0] if dirs else None


def _render_report(
    selected: pd.DataFrame,
    quota: pd.DataFrame,
    *,
    generation_policy: str = "judge_pool_rebuild_v1",
    base_run_id: str = "",
    base_factor_count: int = 0,
    family_report: pd.DataFrame | None = None,
    appeal_provenance: dict | None = None,
    default_eligible: bool = False,
) -> str:
    role_counts = selected["cabinet_role"].value_counts().to_dict() if not selected.empty else {}
    failures = quota[~quota["pass"].astype(bool)].to_dict("records") if not quota.empty else []
    additions = int(selected.get("augmentation_action", pd.Series(dtype=str)).eq("added").sum())
    family_rows = family_report.to_dict("records") if family_report is not None and not family_report.empty else []
    provenance = appeal_provenance or {}
    return "\n".join([
        "# Factor Cabinet Report",
        "",
        f"Generation policy: {generation_policy}",
        f"Base cabinet run: {base_run_id or 'none'}",
        f"Base factor count: {base_factor_count}",
        f"Evidence-backed additions: {additions}",
        f"Appeal source run: {provenance.get('run_id') or 'none'}",
        f"Appeal artifact versions: {provenance.get('artifact_versions') or []}",
        f"PIT Level-2 appeal evaluated: {bool(provenance.get('pit_level2_evaluated'))}",
        f"Orderflow parameter research evaluated: {bool(provenance.get('orderflow_research_evaluated'))}",
        f"Eligible as Web default: {bool(default_eligible)}",
        f"Factor count: {len(selected)}",
        f"Role distribution: {role_counts}",
        f"Quota failures: {failures}",
        f"PIT family inclusion: {family_rows}",
        "",
        "Missing families are reported as no evidence and are never forced into the executable cabinet.",
        "State machine should read factor_cabinet.json only, not raw admitted pools.",
    ])
