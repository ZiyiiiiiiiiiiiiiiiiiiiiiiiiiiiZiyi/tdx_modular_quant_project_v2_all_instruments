"""Family-balanced scoring for the cabinet-native governance mainline."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.factor_semantic_contract import build_factor_semantic_contracts


ROLE_COLUMNS = {
    "entry_alpha": "cabinet_strict_entry_score",
    "entry_alpha_proxy": "cabinet_proxy_entry_score",
    "timing_filter": "cabinet_timing_score",
    "risk_override": "cabinet_risk_safety_score",
    "liquidity_filter": "cabinet_liquidity_health_score",
    "hold_validation": "cabinet_hold_support_score",
    "sell_trigger": "cabinet_sell_safety_score",
}


def attach_cabinet_native_scores(
    candidates: pd.DataFrame,
    proposals: pd.DataFrame,
    *,
    runtime_context,
    strict_weight: float = 0.60,
    max_family_share: float = 0.25,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Attach role scores without allowing factor-count or missingness inflation."""
    if candidates is None or candidates.empty:
        return candidates, pd.DataFrame()
    contracts = build_factor_semantic_contracts(runtime_context)
    if not contracts:
        raise ValueError("cabinet-native scoring requires a factor-cabinet runtime context")
    strict_weight = float(strict_weight)
    if not 0.0 <= strict_weight <= 1.0:
        raise ValueError("strict_weight must be between zero and one")
    if not 0.0 < float(max_family_share) <= 1.0:
        raise ValueError("max_family_share must be in (0, 1]")

    evidence = proposals[["symbol", "model_name", "predicted_return_5d"]].copy()
    evidence["symbol"] = evidence["symbol"].astype(str)
    evidence["model_name"] = evidence["model_name"].astype(str)
    evidence = evidence[evidence["model_name"].isin(contracts)].copy()
    evidence["factor_score"] = (
        evidence.groupby("model_name", sort=False)["predicted_return_5d"]
        .rank(pct=True, method="average")
    )
    evidence = evidence.dropna(subset=["factor_score"])
    evidence["primary_role"] = evidence["model_name"].map(lambda name: contracts[name].primary_role)
    evidence["economic_family"] = evidence["model_name"].map(lambda name: contracts[name].economic_family)
    evidence["near_relative_key"] = evidence["model_name"].map(lambda name: contracts[name].near_relative_key)

    relative = (
        evidence.groupby(
            ["symbol", "primary_role", "economic_family", "near_relative_key"],
            sort=False,
            dropna=False,
        )["factor_score"]
        .median()
        .rename("relative_score")
        .reset_index()
    )
    family = (
        relative.groupby(["symbol", "primary_role", "economic_family"], sort=False, dropna=False)
        .agg(family_score=("relative_score", "median"), relative_count=("near_relative_key", "nunique"))
        .reset_index()
    )
    configured_families: dict[str, set[str]] = {}
    for contract in contracts.values():
        configured_families.setdefault(contract.primary_role, set()).add(contract.economic_family)

    role_frames = []
    family["family_weight"] = 0.0
    for role, configured in configured_families.items():
        active = family[family["primary_role"].eq(role)].copy()
        if active.empty:
            continue
        active_count = active.groupby("symbol")["economic_family"].transform("nunique").clip(lower=1)
        active["family_weight"] = (1.0 / active_count).clip(upper=float(max_family_share))
        # Keep the family cap binding. Unused weight shrinks the role toward neutral.
        active["weighted_deviation"] = active["family_weight"] * (active["family_score"] - 0.5)
        grouped = active.groupby("symbol", sort=False).agg(
            weighted_deviation=("weighted_deviation", "sum"),
            active_family_count=("economic_family", "nunique"),
            family_weight_sum=("family_weight", "sum"),
        )
        grouped["configured_family_count"] = max(len(configured), 1)
        grouped["family_coverage"] = (
            grouped["active_family_count"] / grouped["configured_family_count"]
        ).clip(0.0, 1.0)
        grouped["role_score"] = (
            0.5 + grouped["family_coverage"] * grouped["weighted_deviation"]
        ).clip(0.0, 1.0)
        grouped["primary_role"] = role
        role_frames.append(grouped.reset_index())
        family.loc[active.index, "family_weight"] = active["family_weight"]

    role_scores = pd.concat(role_frames, ignore_index=True) if role_frames else pd.DataFrame()
    output = candidates.copy()
    output["symbol"] = output["symbol"].astype(str)
    if not family.empty:
        family_pivot = family.pivot_table(
            index="symbol", columns="economic_family", values="family_score", aggfunc="median"
        )
        for family_name in family_pivot.columns:
            safe_name = _safe_family_column(family_name)
            mapping = family_pivot[family_name].to_dict()
            output[f"cabinet_family_{safe_name}_score"] = output["symbol"].map(mapping)
        entry_family = family[family["primary_role"].isin({"entry_alpha", "entry_alpha_proxy"})].copy()
        if not entry_family.empty:
            entry_family = entry_family.sort_values(
                ["symbol", "family_score", "economic_family"], ascending=[True, False, True]
            ).drop_duplicates("symbol", keep="first")
            thesis_map = entry_family.set_index("symbol")["economic_family"].to_dict()
            support_map = entry_family.set_index("symbol")["family_score"].to_dict()
            output["cabinet_entry_thesis"] = output["symbol"].map(thesis_map).fillna("composite")
            output["cabinet_entry_thesis_support"] = output["symbol"].map(support_map).fillna(0.5)
    for role, column in ROLE_COLUMNS.items():
        if role_scores.empty:
            mapping = {}
            coverage = {}
        else:
            subset = role_scores[role_scores["primary_role"].eq(role)]
            mapping = subset.set_index("symbol")["role_score"].to_dict()
            coverage = subset.set_index("symbol")["family_coverage"].to_dict()
        output[column] = output["symbol"].map(mapping).fillna(0.5).astype(float)
        output[f"{column}_coverage"] = output["symbol"].map(coverage).fillna(0.0).astype(float)

    strict = output["cabinet_strict_entry_score"]
    proxy = output["cabinet_proxy_entry_score"]
    timing_adjustment = (output["cabinet_timing_score"] - 0.5).clip(-0.15, 0.15)
    liquidity_penalty = ((0.5 - output["cabinet_liquidity_health_score"]).clip(lower=0.0) * 0.20).clip(0.0, 0.10)
    output["cabinet_base_entry_score"] = strict_weight * strict + (1.0 - strict_weight) * proxy
    output["cabinet_timing_adjustment"] = timing_adjustment
    output["cabinet_liquidity_penalty"] = liquidity_penalty
    output["cabinet_native_final_score"] = (
        output["cabinet_base_entry_score"] + timing_adjustment - liquidity_penalty
    ).clip(0.0, 1.0)
    output["primary_score"] = output["cabinet_native_final_score"]
    output["score_authority"] = "cabinet_native_family_balanced_v1"
    output = output.sort_values(["primary_score", "symbol"], ascending=[False, True])
    output["candidate_rank"] = range(1, len(output) + 1)
    return output, family


def _safe_family_column(value: object) -> str:
    text = "".join(char if str(char).isalnum() else "_" for char in str(value).lower())
    return text.strip("_") or "unknown"
