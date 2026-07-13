"""Versioned economic taxonomy and reduced experiment contracts for cabinets."""
from __future__ import annotations

import hashlib
import json

import pandas as pd


TAXONOMY_VERSION = "cabinet_economic_taxonomy_v1"
VIEW_REMOVALS = {
    "cabinet_full": frozenset(),
    "cabinet_minus_momentum": frozenset({"directional_momentum"}),
    "cabinet_minus_reversal": frozenset({"reversal_timing"}),
    "cabinet_minus_liquidity_volatility": frozenset({"liquidity_execution", "volatility_risk"}),
}


def build_cabinet_module_mapping(spec) -> pd.DataFrame:
    if spec is None or not getattr(spec, "uses_factor_cabinet", False):
        return pd.DataFrame()
    rows = []
    for name in getattr(spec, "alpha_models", ()):
        formula_module = str((spec.module_map or {}).get(name, ""))
        family = str((spec.family_map or {}).get(name, ""))
        role = str((spec.role_map or {}).get(name, ""))
        primary, reason = _economic_module(name, formula_module, family)
        rows.append({
            "taxonomy_version": TAXONOMY_VERSION,
            "factor_name": str(name),
            "raw_column": str((spec.model_feature_map or {}).get(name, "")),
            "formula_module": formula_module,
            "family": family,
            "role": role,
            "primary_economic_module": primary,
            "mapping_reason": reason,
        })
    return pd.DataFrame(rows).sort_values(["primary_economic_module", "role", "factor_name"]).reset_index(drop=True)


def build_cabinet_experiment_contracts(mapping: pd.DataFrame) -> pd.DataFrame:
    if mapping is None or mapping.empty:
        return pd.DataFrame()
    rows = []
    for view_name, removals in VIEW_REMOVALS.items():
        active = mapping[~mapping["primary_economic_module"].isin(removals)].copy()
        roles = active["role"].value_counts().to_dict()
        factors = sorted(active["factor_name"].astype(str).tolist())
        valid, reasons = _role_contract(roles, len(factors))
        rows.append({
            "taxonomy_version": TAXONOMY_VERSION,
            "view_name": view_name,
            "removed_modules": "|".join(sorted(removals)),
            "factor_count": int(len(factors)),
            "factor_name_hash": hashlib.sha256("\n".join(factors).encode("utf-8")).hexdigest(),
            "role_distribution": json.dumps({str(k): int(v) for k, v in sorted(roles.items())}, sort_keys=True),
            "module_distribution": json.dumps(
                {str(k): int(v) for k, v in sorted(active["primary_economic_module"].value_counts().to_dict().items())},
                sort_keys=True,
            ),
            "contract_valid": bool(valid),
            "contract_reasons": "|".join(reasons) if reasons else "passed",
        })
    result = pd.DataFrame(rows)
    duplicate_hash = result["factor_name_hash"].duplicated(keep=False)
    result["duplicate_view_hash"] = duplicate_hash
    result.loc[duplicate_hash, "contract_valid"] = False
    result.loc[duplicate_hash, "contract_reasons"] = result.loc[duplicate_hash, "contract_reasons"].astype(str) + "|duplicate_factor_view"
    return result


def _economic_module(name: str, module: str, family: str) -> tuple[str, str]:
    text = "|".join([str(name), str(module), str(family)]).lower()
    if "breakout" in text or "price_pos" in text:
        return "breakout_confirmation", "breakout_or_price_position"
    if "liquidity" in text or "amihud" in text or "turnover" in text or "amount" in text:
        return "liquidity_execution", "liquidity_or_market_impact_proxy"
    if "volatility" in text or "vol_neg" in text or "downvol" in text:
        return "volatility_risk", "volatility_or_downside_volatility"
    if "reversal" in text or "rev" in text:
        return "reversal_timing", "reversal_formula"
    if "momentum" in text or "ret_" in text or "ret+" in text:
        return "directional_momentum", "return_or_momentum_formula"
    if "barra" in text or "size" in text:
        return "size_style", "size_or_barra_style"
    return "other", "unclassified_review_required"


def _role_contract(roles: dict, factor_count: int) -> tuple[bool, list[str]]:
    reasons = []
    if factor_count <= 0:
        reasons.append("empty_view")
    if int(roles.get("entry_alpha", 0)) + int(roles.get("entry_alpha_proxy", 0)) < 3:
        reasons.append("entry_support_below_min")
    if int(roles.get("timing_filter", 0)) < 1:
        reasons.append("timing_support_missing")
    if int(roles.get("risk_override", 0)) < 1:
        reasons.append("risk_support_missing")
    if int(roles.get("liquidity_filter", 0)) < 1:
        reasons.append("liquidity_support_missing")
    if int(roles.get("hold_validation", 0)) < 1:
        reasons.append("hold_support_missing")
    return not reasons, reasons
