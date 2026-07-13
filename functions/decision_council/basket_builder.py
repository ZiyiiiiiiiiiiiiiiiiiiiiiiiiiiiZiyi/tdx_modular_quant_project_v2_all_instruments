"""Build diversified stock baskets from scored daily candidates."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class BasketBuildConfig:
    min_names: int = 3
    max_names: int = 8
    stable_weight: float = 0.50
    aggressive_weight: float = 0.30
    reserve_weight: float = 0.20
    max_same_module: int = 2
    max_same_family: int = 1
    max_same_sector: int = 2
    min_score: float = 0.0


def build_candidate_baskets(candidates: pd.DataFrame, *, config: BasketBuildConfig | None = None) -> pd.DataFrame:
    """Select non-near-relative names into stable/aggressive/reserve sleeves."""
    config = config or BasketBuildConfig()
    if candidates is None or candidates.empty:
        return _empty_basket()
    data = candidates.copy()
    for column in ("symbol", "module", "family", "near_relative_key", "prototype_sector"):
        if column not in data.columns:
            data[column] = ""
    score_col = _score_column(data)
    data[score_col] = pd.to_numeric(data[score_col], errors="coerce").fillna(0.0)
    data = data[data[score_col] >= float(config.min_score)].sort_values([score_col, "symbol"], ascending=[False, True])
    selected = _select_diverse(data, config=config, limit=int(config.max_names))
    if selected.empty or len(selected) < int(config.min_names):
        return _empty_basket()
    selected = selected.copy()
    selected["basket_role"] = _assign_basket_roles(len(selected), config=config)
    selected["basket_weight"] = selected["basket_role"].map(
        {
            "stable_core": float(config.stable_weight),
            "aggressive_satellite": float(config.aggressive_weight),
            "reserve_replacement": float(config.reserve_weight),
        }
    )
    selected["basket_weight"] = selected["basket_weight"] / selected.groupby("basket_role")["basket_weight"].transform("sum").replace(0.0, 1.0)
    selected["basket_score"] = float(selected[score_col].mean())
    selected["basket_name_count"] = int(len(selected))
    selected["basket_module_count"] = int(selected["module"].nunique())
    selected["basket_family_count"] = int(selected["family"].nunique())
    return selected.reset_index(drop=True)


def _select_diverse(data: pd.DataFrame, *, config: BasketBuildConfig, limit: int) -> pd.DataFrame:
    rows = []
    module_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}
    sector_counts: dict[str, int] = {}
    used_relatives: set[str] = set()
    for _, row in data.iterrows():
        module = str(row.get("module", ""))
        family = str(row.get("family", ""))
        sector = str(row.get("prototype_sector", ""))
        relative = str(row.get("near_relative_key", "") or f"{module}:{family}:{row.get('symbol', '')}")
        if relative in used_relatives:
            continue
        if module_counts.get(module, 0) >= int(config.max_same_module):
            continue
        if family_counts.get(family, 0) >= int(config.max_same_family):
            continue
        if sector and sector_counts.get(sector, 0) >= int(config.max_same_sector):
            continue
        rows.append(row)
        used_relatives.add(relative)
        module_counts[module] = module_counts.get(module, 0) + 1
        family_counts[family] = family_counts.get(family, 0) + 1
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        if len(rows) >= int(limit):
            break
    return pd.DataFrame(rows)


def _assign_basket_roles(count: int, *, config: BasketBuildConfig) -> list[str]:
    stable_count = max(1, round(int(count) * float(config.stable_weight)))
    aggressive_count = max(1, round(int(count) * float(config.aggressive_weight)))
    roles = ["stable_core"] * stable_count + ["aggressive_satellite"] * aggressive_count
    roles.extend(["reserve_replacement"] * max(int(count) - len(roles), 0))
    return roles[: int(count)]


def _score_column(data: pd.DataFrame) -> str:
    for column in ("retail_executable_score", "final_entry_score", "primary_score", "alpha_score"):
        if column in data.columns:
            return column
    data["primary_score"] = 0.0
    return "primary_score"


def _empty_basket() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "symbol",
            "basket_role",
            "basket_weight",
            "basket_score",
            "basket_name_count",
            "basket_module_count",
            "basket_family_count",
        ]
    )
