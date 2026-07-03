"""Centralized allocation constraints for basket governance."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class AllocationConstraintConfig:
    max_single_weight: float = 0.20
    max_module_weight: float = 0.35
    max_family_weight: float = 0.25
    max_sector_weight: float = 0.35
    max_turnover_weight: float = 0.20


def apply_allocation_constraints(weights: pd.DataFrame, *, config: AllocationConstraintConfig | None = None) -> tuple[pd.DataFrame, dict]:
    config = config or AllocationConstraintConfig()
    if weights is None or weights.empty:
        return pd.DataFrame(), {"constraint_pass": False, "reason": "empty_weights"}
    data = weights.copy()
    data["target_weight"] = pd.to_numeric(data.get("target_weight", data.get("basket_weight")), errors="coerce").fillna(0.0)
    data["target_weight"] = data["target_weight"].clip(lower=0.0, upper=float(config.max_single_weight))
    data = _cap_group(data, "module", float(config.max_module_weight))
    data = _cap_group(data, "family", float(config.max_family_weight))
    data = _cap_group(data, "prototype_sector", float(config.max_sector_weight))
    total = float(data["target_weight"].sum())
    if total > 1.0:
        data["target_weight"] = data["target_weight"] / total
    diagnostics = {
        "constraint_pass": bool(float(data["target_weight"].sum()) > 0.0),
        "max_single_weight": float(data["target_weight"].max()) if not data.empty else 0.0,
        "module_count": int(data.get("module", pd.Series(dtype=object)).nunique()),
        "family_count": int(data.get("family", pd.Series(dtype=object)).nunique()),
        "target_exposure": float(data["target_weight"].sum()),
    }
    return data, diagnostics


def _cap_group(data: pd.DataFrame, column: str, cap: float) -> pd.DataFrame:
    if column not in data.columns:
        return data
    out = data.copy()
    for value, group in out.groupby(column, dropna=False):
        total = float(group["target_weight"].sum())
        if total > cap and total > 0.0:
            out.loc[group.index, "target_weight"] = group["target_weight"] * (cap / total)
    return out
