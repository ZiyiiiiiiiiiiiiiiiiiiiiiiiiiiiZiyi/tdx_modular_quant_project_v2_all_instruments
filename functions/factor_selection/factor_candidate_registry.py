"""Build a complete factor candidate registry, including visible vacancies."""
from __future__ import annotations

import pandas as pd

from functions.factor_selection.factor_family_contract import (
    candidate_catalog_frame,
    canonical_family,
)


CANDIDATE_REGISTRY_VERSION = "factor_candidate_registry_v1"


def build_factor_candidate_registry(
    observed_candidates: pd.DataFrame | None,
    *,
    available_columns=(),
    pit_level2_state: str = "degraded",
    temporal_isolation_pass: bool = False,
) -> pd.DataFrame:
    catalog = candidate_catalog_frame()
    observed = observed_candidates.copy() if observed_candidates is not None else pd.DataFrame()
    if not observed.empty:
        if "factor_name" not in observed:
            raise ValueError("observed factor candidates require factor_name")
        observed = observed.drop_duplicates("factor_name", keep="last")
        merged = catalog.merge(observed, on="factor_name", how="outer", suffixes=("_catalog", ""))
        for column in catalog.columns:
            catalog_column = f"{column}_catalog"
            if catalog_column in merged:
                if column not in merged:
                    merged[column] = merged[catalog_column]
                else:
                    merged[column] = merged[column].where(merged[column].notna(), merged[catalog_column])
                merged = merged.drop(columns=catalog_column)
    else:
        merged = catalog.copy()
    for column in ("raw_column", "family", "module", "allowed_roles", "direction", "pit_requirement"):
        if column not in merged:
            merged[column] = ""
    merged["family"] = [
        canonical_family(family, factor_name=name, module=module)
        for family, name, module in zip(merged["family"], merged["factor_name"], merged["module"])
    ]
    available = {str(column) for column in available_columns}
    merged["runtime_column_available"] = merged["raw_column"].astype(str).isin(available)
    pit_required = merged["pit_requirement"].astype(str).str.startswith("pit_level2")
    merged["pit_status"] = "not_required"
    merged.loc[pit_required, "pit_status"] = (
        "formal" if str(pit_level2_state) == "available"
        else ("research" if str(pit_level2_state) == "research_only" else "blocked")
    )
    merged["temporal_isolation_pass"] = bool(temporal_isolation_pass)
    if "negative_control_pass" not in merged:
        merged["negative_control_pass"] = False
    merged["candidate_status"] = "pending_evidence"
    merged.loc[~merged["runtime_column_available"], "candidate_status"] = "pending_missing_runtime_column"
    merged.loc[merged["pit_status"].eq("blocked"), "candidate_status"] = "blocked_pit"
    merged["candidate_registry_version"] = CANDIDATE_REGISTRY_VERSION
    return merged.sort_values(["family", "factor_name"]).reset_index(drop=True)
