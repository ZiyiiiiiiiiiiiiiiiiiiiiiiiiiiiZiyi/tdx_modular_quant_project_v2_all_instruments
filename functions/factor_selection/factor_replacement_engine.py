"""Same-family replacement without lowering evidence standards."""
from __future__ import annotations

import numpy as np
import pandas as pd

from functions.factor_selection.factor_family_contract import FAMILY_CONTRACTS, canonical_family


REPLACEMENT_ENGINE_VERSION = "same_family_replacement_v1"


def build_replacement_plan(
    current_cabinet: pd.DataFrame,
    candidate_registry: pd.DataFrame,
    *,
    removed_factors=(),
) -> dict[str, pd.DataFrame]:
    if "factor_name" not in current_cabinet or "factor_name" not in candidate_registry:
        raise ValueError("replacement planning requires factor_name in cabinet and registry")
    removed = {str(name) for name in removed_factors}
    cabinet = current_cabinet.copy()
    registry = candidate_registry.copy()
    for frame in (cabinet, registry):
        if "family" not in frame:
            frame["family"] = "unknown"
        if "role" not in frame:
            frame["role"] = frame.get("new_role", "")
        frame["family"] = [
            canonical_family(family, factor_name=name, module=module)
            for family, name, module in zip(
                frame["family"], frame["factor_name"], frame.get("module", pd.Series("", index=frame.index))
            )
        ]
    kept = cabinet[~cabinet["factor_name"].astype(str).isin(removed)].copy()
    chosen = set(kept["factor_name"].astype(str))
    audit_rows = []
    capacity_rows = []
    additions = []
    contracts = {item.family: item for item in FAMILY_CONTRACTS}
    quality = _quality_score(registry)
    registry["_replacement_quality"] = quality
    for family, contract in contracts.items():
        active = kept[kept["family"].eq(family)]
        before_count = int(len(active))
        vacancies = max(int(contract.target_min) - before_count, 0)
        pool = registry[
            registry["family"].eq(family)
            & registry.get("replacement_eligible", pd.Series(False, index=registry.index)).fillna(False).astype(bool)
            & ~registry["factor_name"].astype(str).isin(chosen)
        ].sort_values(["_replacement_quality", "factor_name"], ascending=[False, True])
        if contract.selection_mode != "direct":
            pool = pool.iloc[0:0]
            vacancies = 0
        selected_pool = pool.head(min(vacancies, max(contract.target_max - before_count, 0)))
        for _, row in selected_pool.iterrows():
            name = str(row["factor_name"])
            additions.append(row.drop(labels=["_replacement_quality"]).to_dict())
            chosen.add(name)
            audit_rows.append({
                "removed_factor": "", "removed_family": family,
                "removed_role": "", "removal_reason": "family_below_target_min",
                "replacement_attempted": True, "replacement_candidate_count": int(len(pool)),
                "replacement_factor": name, "replacement_status": "selected_same_family",
                "vacancy_reason": "", "replacement_engine_version": REPLACEMENT_ENGINE_VERSION,
            })
        remaining = vacancies - len(selected_pool)
        for _ in range(max(int(remaining), 0)):
            audit_rows.append({
                "removed_factor": "", "removed_family": family,
                "removed_role": "", "removal_reason": "family_below_target_min",
                "replacement_attempted": True, "replacement_candidate_count": int(len(pool)),
                "replacement_factor": "", "replacement_status": "vacant_no_qualified_candidate",
                "vacancy_reason": _vacancy_reason(registry[registry["family"].eq(family)]),
                "replacement_engine_version": REPLACEMENT_ENGINE_VERSION,
            })
        after_count = before_count + len(selected_pool)
        status = (
            "FULL" if after_count >= contract.target_min
            else _family_status(registry[registry["family"].eq(family)], after_count)
        )
        capacity_rows.append({
            "family": family, "target_min": contract.target_min, "target_max": contract.target_max,
            "before_count": before_count, "replacement_count": int(len(selected_pool)),
            "after_count": after_count, "qualified_candidate_count": int(len(pool)),
            "family_status": status, "selection_mode": contract.selection_mode,
            "replacement_engine_version": REPLACEMENT_ENGINE_VERSION,
        })
    for name in sorted(removed):
        row = cabinet[cabinet["factor_name"].astype(str).eq(name)]
        family = str(row.iloc[0]["family"]) if not row.empty else "unknown"
        role = str(row.iloc[0].get("role", "")) if not row.empty else ""
        if not any(item.get("removed_family") == family for item in audit_rows):
            audit_rows.append({
                "removed_factor": name, "removed_family": family, "removed_role": role,
                "removal_reason": "explicit_prune", "replacement_attempted": True,
                "replacement_candidate_count": 0, "replacement_factor": "",
                "replacement_status": "family_capacity_already_satisfied",
                "vacancy_reason": "", "replacement_engine_version": REPLACEMENT_ENGINE_VERSION,
            })
    additions_frame = pd.DataFrame(additions)
    rebuilt = pd.concat([kept, additions_frame], ignore_index=True, sort=False)
    return {
        "rebuilt_cabinet": rebuilt,
        "replacement_audit": pd.DataFrame(audit_rows),
        "family_capacity": pd.DataFrame(capacity_rows),
        "replacement_additions": additions_frame,
    }


def _quality_score(data: pd.DataFrame) -> pd.Series:
    ic_ir = _numeric_series(data, "best_ic_ir", "ic_ir")
    spread = _numeric_series(data, "best_cost_adjusted_top_bottom_spread", "cost_adjusted_top_bottom_spread")
    consistency = _numeric_series(data, "positive_ic_ratio")
    turnover = _numeric_series(data, "avg_turnover_mean", "avg_turnover")
    redundancy = _numeric_series(data, "redundancy_penalty")
    return ic_ir + spread + consistency - turnover - redundancy


def _numeric_series(data: pd.DataFrame, primary: str, fallback: str = "") -> pd.Series:
    if primary in data:
        values = data[primary]
    elif fallback and fallback in data:
        values = data[fallback]
    else:
        values = pd.Series(0.0, index=data.index)
    return pd.to_numeric(values, errors="coerce").fillna(0.0)


def _vacancy_reason(data: pd.DataFrame) -> str:
    if data.empty:
        return "candidate_family_not_registered"
    if data.get("pit_status", pd.Series("", index=data.index)).astype(str).eq("blocked").all():
        return "all_candidates_blocked_pit"
    if not data.get("runtime_column_available", pd.Series(False, index=data.index)).fillna(False).astype(bool).any():
        return "no_runtime_feature_column"
    return "no_candidate_passed_predictive_evidence"


def _family_status(data: pd.DataFrame, count: int) -> str:
    if count > 0:
        return "PARTIAL"
    if not data.empty and data.get("pit_status", pd.Series("", index=data.index)).astype(str).eq("blocked").all():
        return "BLOCKED_PIT"
    return "VACANT"
