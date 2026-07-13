"""Verify diversified_pre_screen_bundle_v2 structural admission rules.

Run:
& "C:\\Users\\Ziyi Wang\\.conda\\envs\\stock_ai\\python.exe" verify_diversified_pre_screen_bundle_v2.py
"""
from __future__ import annotations

import sys

import pandas as pd

from config import (
    GOVERNANCE_ALPHA_DIVERSIFICATION_RULES,
    GOVERNANCE_DIVERSIFIED_PRE_SCREEN_BUNDLE_V2_ROLE_MAP,
    GOVERNANCE_FACTOR_JUDGED_ALPHA_WEIGHTS,
)
from functions.alpha_bundles import ALPHA_BUNDLE_REGISTRY
from functions.decision_council.analytics import factor_module
from functions.decision_council.candidate_factor_cache import (
    load_pre_screen_candidate_factor_cache,
    pre_screen_candidate_raw_columns,
)
from functions.decision_council.quality_reports import build_alpha_diversification_report


FAST_JUDGE_SUMMARY = (
    "results/decision_council/fast_factor_judge/hs300_csi500_a500_strict/"
    "run20260701_201606_233579/fast_factor_summary.csv"
)


def _family(model_name: str) -> str:
    name = str(model_name).lower()
    if name.startswith("candidate_grid_rank_ratio__rev") and "amihud" in name:
        return "rev_amihud_ratio_grid"
    if name.startswith("candidate_grid_rank_spread__rev") and "amihud" in name:
        return "rev_amihud_spread_grid"
    if name.startswith("candidate_grid_rank_product__ret") and "__rev_" in name:
        return "ret_reversal_interaction_grid"
    if name.startswith("candidate_grid_rank_product__rev") and "__rev_" in name:
        return "reversal_interaction_grid"
    if name.startswith("candidate_grid_rank_product__rev") and "__size_" in name:
        return "rev_size_interaction_grid"
    if name.startswith("candidate_grid_rank_gate_hi__ret") and "__size_" in name:
        return "ret_size_conditional_grid"
    if name.startswith("candidate_grid_rank_gate_hi__rev") and "__size_" in name:
        return "rev_size_conditional_grid"
    if name.startswith("candidate_grid_rank_mean__rev") and "__rev_" in name:
        return "short_medium_reversal_blend_grid"
    if name.startswith("candidate_grid_base_rank__rev"):
        return "single_reversal_grid"
    if name.startswith("candidate_grid_base_rank__vol"):
        return "single_volatility_grid"
    if name.startswith("candidate_grid_base_rank__downvol"):
        return "single_downside_volatility_grid"
    if name.startswith("candidate_size_") or name.startswith("candidate_grid_base_rank__size"):
        return "size_style"
    if name.startswith("candidate_idiosyncratic_vol"):
        return "idiosyncratic_volatility_defense"
    if name.startswith("candidate_downside_volatility"):
        return "downside_volatility_defense"
    if "size_total" in name or "size_float" in name:
        return "size_conditioned_grid"
    if "volatility" in name or "vol_neg" in name or "idiosyncratic_vol" in name:
        return "volatility_defense"
    if "orderflow" in name or "volume" in name or "close_strength" in name:
        return "flow_close"
    if "limit" in name or "event" in name or "holiday" in name:
        return "event_limit"
    if "momentum" in name or "macd" in name or "breakout" in name or "ma_" in name:
        return "trend"
    if "reversal" in name or "decline" in name or "oversold" in name or "pullback" in name:
        return "reversal_pullback"
    return name.split("__")[0]


def _cache_backed_proposals(models: list[str]) -> pd.DataFrame:
    cache = load_pre_screen_candidate_factor_cache("2024-01-01", "2024-01-10", alpha_models=tuple(models))
    raw_map = dict(zip(models, pre_screen_candidate_raw_columns(tuple(models))))
    rows = []
    for model, raw_column in raw_map.items():
        if raw_column not in cache.columns:
            continue
        ranks = pd.to_numeric(cache[raw_column], errors="coerce").rank(pct=True).fillna(0.5)
        values = ranks * 0.02 - 0.01
        for decision_date, symbol, value in zip(cache["date"], cache["symbol"], values):
            rows.append(
                {
                    "decision_date": decision_date,
                    "symbol": symbol,
                    "model_name": model,
                    "predicted_return_5d": float(value),
                    "prediction_std": 0.02,
                    "reputation_weight": float(GOVERNANCE_FACTOR_JUDGED_ALPHA_WEIGHTS.get(model, 1.0)),
                }
            )
    return pd.DataFrame(rows)


def main() -> int:
    failures: list[str] = []
    spec = ALPHA_BUNDLE_REGISTRY.get("diversified_pre_screen_bundle_v2")
    models = ALPHA_BUNDLE_REGISTRY.get_alpha_model_names("diversified_pre_screen_bundle_v2")
    modules = pd.Series([factor_module(model) for model in models])
    families = pd.Series([_family(model) for model in models])
    weights = pd.Series(
        [float(GOVERNANCE_FACTOR_JUDGED_ALPHA_WEIGHTS.get(model, 1.0)) for model in models],
        index=list(models),
    ).clip(lower=0.0)
    module_weight_share = weights.groupby([factor_module(model) for model in models]).sum() / max(float(weights.sum()), 1e-12)
    role_counts: dict[str, int] = {}
    for model in models:
        for role in GOVERNANCE_DIVERSIFIED_PRE_SCREEN_BUNDLE_V2_ROLE_MAP.get(model, ()):
            role_counts[str(role)] = role_counts.get(str(role), 0) + 1
    judge = pd.read_csv(FAST_JUDGE_SUMMARY)
    admitted_pool = judge[judge["verdict"].isin(["promote_candidate", "watchlist"])].copy()
    admitted_names = set(admitted_pool["factor_name"].astype(str))

    rules = GOVERNANCE_ALPHA_DIVERSIFICATION_RULES
    if spec.status != "active":
        failures.append("diversified_pre_screen_bundle_v2 is not active")
    if len(models) < 6 or len(models) > 12:
        failures.append(f"unexpected model count: {len(models)}")
    non_candidate = [model for model in models if not str(model).startswith("candidate_")]
    if non_candidate:
        failures.append(f"v2 contains non-candidate models: {non_candidate}")
    missing_from_pool = sorted(set(models) - admitted_names)
    if missing_from_pool:
        failures.append(f"v2 models missing from 486+114 judge pool: {missing_from_pool}")
    if int(modules.nunique()) < int(rules["min_distinct_modules"]):
        failures.append(f"distinct module count too low: {int(modules.nunique())}")
    if int(families.nunique()) < int(rules["min_distinct_families"]):
        failures.append(f"distinct family count too low: {int(families.nunique())}")
    if float(module_weight_share.max()) > float(rules["max_module_weight_share"]):
        failures.append(f"module weight share too high: {float(module_weight_share.max()):.4f}")
    if float(module_weight_share.get("range_grid", 0.0)) > float(rules["range_grid_max_weight_share"]):
        failures.append(f"range_grid weight share too high: {float(module_weight_share.get('range_grid', 0.0)):.4f}")
    for required_role in ("entry_alpha", "timing_filter", "risk_override"):
        if role_counts.get(required_role, 0) <= 0:
            failures.append(f"required role missing: {required_role}")

    diversification = build_alpha_diversification_report(_cache_backed_proposals(list(models)))
    if diversification.empty or not bool(diversification["pass_flag"].iloc[0]):
        reason = diversification["block_reasons"].iloc[0] if not diversification.empty else "empty_report"
        failures.append(f"cache-backed diversification report failed: {reason}")

    if failures:
        for failure in failures:
            print(f"[FAIL] {failure}")
        return 1
    print("[PASS] diversified_pre_screen_bundle_v2 is registered and active")
    print(f"[PASS] model_count={len(models)}, modules={int(modules.nunique())}, families={int(families.nunique())}")
    print(f"[PASS] max_module_weight_share={float(module_weight_share.max()):.4f}")
    print(f"[PASS] range_grid_weight_share={float(module_weight_share.get('range_grid', 0.0)):.4f}")
    print(f"[PASS] role_counts={role_counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
