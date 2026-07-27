"""Build auditable research/formal cabinets with same-family replacement.

This module deliberately fails closed: an overlapping factor-selection lineage
may still be emitted as a research cabinet, but it can never be promoted to the
formal cabinet.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

import pandas as pd

from functions.factor_selection.factor_candidate_registry import build_factor_candidate_registry
from functions.factor_selection.factor_evidence_grade import EvidenceThresholds, grade_factor_evidence
from functions.factor_selection.factor_family_contract import candidate_catalog_frame, family_contract_frame
from functions.factor_selection.factor_replacement_engine import build_replacement_plan
from functions.research.temporal_contract import audit_artifact_lineage, write_temporal_audit


CLEAN_CABINET_VERSION = "clean_factor_cabinet_v1"
OUTPUT_ROOT = Path("results/factor_cabinet_clean")


def build_clean_factor_cabinets(
    *,
    source_cabinet_path: str | Path,
    oos_start,
    removed_factors=(),
    observed_candidates: pd.DataFrame | None = None,
    available_columns=(),
    pit_level2_state: str = "degraded",
    output_root: str | Path = OUTPUT_ROOT,
    thresholds: EvidenceThresholds = EvidenceThresholds(),
) -> dict[str, Path]:
    source_path = Path(source_cabinet_path)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    source = pd.DataFrame(payload.get("factors", []))
    if source.empty or "factor_name" not in source:
        raise ValueError("source factor cabinet must contain factors with factor_name")

    lineage, temporal = audit_artifact_lineage(source_path, oos_start=oos_start)
    inferred_columns = set(str(value) for value in source.get("raw_column", pd.Series(dtype=str)).dropna())
    inferred_columns.update(str(value) for value in available_columns)
    observed = _merge_observed(source, observed_candidates)
    registry = build_factor_candidate_registry(
        observed,
        available_columns=inferred_columns,
        pit_level2_state=pit_level2_state,
        temporal_isolation_pass=bool(temporal["temporal_isolation_pass"]),
    )
    registry = grade_factor_evidence(registry, thresholds=thresholds)
    replacement = build_replacement_plan(source, registry, removed_factors=removed_factors)
    research = replacement["rebuilt_cabinet"].copy()

    # Promotion is an artifact-level decision.  A cabinet whose discovery
    # lineage overlaps the requested OOS window has no formally eligible rows.
    formal_eligible = bool(temporal["temporal_isolation_pass"]) and str(pit_level2_state) == "available"
    formal = research.copy() if formal_eligible else research.iloc[0:0].copy()
    run_id = "clean_" + datetime.now().strftime("run%Y%m%d_%H%M%S_%f")
    output = Path(output_root) / run_id
    output.mkdir(parents=True, exist_ok=False)

    temporal_paths = write_temporal_audit(output, lineage, temporal)
    family_contract_frame().to_csv(output / "factor_family_contract.csv", index=False, encoding="utf-8-sig")
    candidate_catalog_frame().to_csv(output / "factor_candidate_catalog.csv", index=False, encoding="utf-8-sig")
    registry.to_csv(output / "factor_candidate_registry.csv", index=False, encoding="utf-8-sig")
    replacement["replacement_audit"].to_csv(output / "factor_replacement_audit.csv", index=False, encoding="utf-8-sig")
    replacement["family_capacity"].to_csv(output / "factor_family_capacity.csv", index=False, encoding="utf-8-sig")
    research.to_csv(output / "research_factor_cabinet.csv", index=False, encoding="utf-8-sig")
    formal.to_csv(output / "formal_factor_cabinet.csv", index=False, encoding="utf-8-sig")

    common = {
        "run_id": run_id,
        "clean_cabinet_version": CLEAN_CABINET_VERSION,
        "source_run_id": str(payload.get("run_id") or source_path.parent.name),
        "source_factor_cabinet_path": str(source_path.resolve()),
        "oos_start": pd.Timestamp(oos_start).strftime("%Y-%m-%d"),
        "pit_level2_state": str(pit_level2_state),
        "temporal_contract": temporal,
        "removed_factors": sorted(str(value) for value in removed_factors),
        "family_capacity": replacement["family_capacity"].to_dict("records"),
    }
    research_payload = {
        **common, "artifact_type": "factor_cabinet_clean_research",
        "formal_eligible": False, "default_eligible": False,
        "factors": _records(research),
    }
    formal_payload = {
        **common, "artifact_type": "factor_cabinet_clean_formal",
        "formal_eligible": formal_eligible, "default_eligible": formal_eligible,
        "factors": _records(formal),
    }
    research_path = output / "research_factor_cabinet.json"
    formal_path = output / "formal_factor_cabinet.json"
    research_path.write_text(json.dumps(research_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    formal_path.write_text(json.dumps(formal_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        **common,
        "source_factor_count": int(len(source)),
        "research_factor_count": int(len(research)),
        "formal_factor_count": int(len(formal)),
        "replacement_count": int(len(replacement["replacement_additions"])),
        "vacant_family_count": int(replacement["family_capacity"]["family_status"].ne("FULL").sum()),
        "formal_eligible": formal_eligible,
        "promotion_blockers": _promotion_blockers(temporal, pit_level2_state),
    }
    summary_path = output / "clean_cabinet_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "output_dir": output,
        "research_factor_cabinet": research_path,
        "formal_factor_cabinet": formal_path,
        "summary": summary_path,
        "temporal_contract": temporal_paths["summary"],
        "candidate_registry": output / "factor_candidate_registry.csv",
        "replacement_audit": output / "factor_replacement_audit.csv",
        "family_capacity": output / "factor_family_capacity.csv",
    }


def _merge_observed(source: pd.DataFrame, observed: pd.DataFrame | None) -> pd.DataFrame:
    base = source.copy()
    if "coverage" not in base:
        base["coverage"] = 0.0
    if observed is None or observed.empty:
        return base
    if "factor_name" not in observed:
        raise ValueError("observed_candidates requires factor_name")
    return pd.concat([base, observed], ignore_index=True, sort=False).drop_duplicates("factor_name", keep="last")


def _promotion_blockers(temporal: dict, pit_state: str) -> list[str]:
    blockers = list(temporal.get("failures", []))
    if str(pit_state) != "available":
        blockers.append("pit_level2_not_formally_available")
    return blockers


def _records(frame: pd.DataFrame) -> list[dict]:
    return json.loads(frame.to_json(orient="records", date_format="iso"))
