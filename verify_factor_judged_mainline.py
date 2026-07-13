"""Verify the fast-judge filtered governance mainline wiring.

Run:
& "C:\\Users\\Ziyi Wang\\.conda\\envs\\stock_ai\\python.exe" verify_factor_judged_mainline.py
"""
from __future__ import annotations

import sys

import pandas as pd

from config import GOVERNANCE_FACTOR_JUDGED_ALPHA_WEIGHTS
from functions.alpha_bundles import ALPHA_BUNDLE_REGISTRY
from functions.decision_council.proposals import build_rule_alpha_proposals
from functions.governance_variant_registry import get_governance_variant_spec


def main() -> int:
    failures: list[str] = []
    bundle = ALPHA_BUNDLE_REGISTRY.get("formal_defensive_bundle")
    compat_bundle = ALPHA_BUNDLE_REGISTRY.get("judged_core_bundle")
    models = ALPHA_BUNDLE_REGISTRY.get_alpha_model_names("formal_defensive_bundle")
    if not models:
        failures.append("formal_defensive_bundle has no runnable governance models")
    if any(GOVERNANCE_FACTOR_JUDGED_ALPHA_WEIGHTS.get(model, 0.0) <= 0.0 for model in models):
        failures.append("formal_defensive_bundle contains a zero-weight model")
    if compat_bundle.status != "deprecated":
        failures.append("judged_core_bundle compatibility alias should be deprecated")

    mainline = get_governance_variant_spec("rules_based_president")
    if mainline.alpha_bundle != "formal_defensive_bundle":
        failures.append("rules_based_president does not use formal_defensive_bundle")
    if mainline.extra.get("selection_weight_mode") != "factor_judged":
        failures.append("rules_based_president does not use factor_judged selection")

    sample = pd.DataFrame(
        {
            "symbol": ["sh600001", "sh600002"],
            "score_grid_trading": [10.0, 1.0],
            "score_limit_up_follow": [1.0, 10.0],
            "volatility_20": [0.02, 0.02],
        }
    )
    proposals = build_rule_alpha_proposals(
        sample,
        reputation_weights={"grid_trading": 1.0, "limit_up_follow": 1.0},
        model_names=("grid_trading", "limit_up_follow"),
        factor_judged=True,
    )
    grid = proposals[proposals["model_name"].eq("grid_trading")].set_index("symbol")
    limit_up = proposals[proposals["model_name"].eq("limit_up_follow")].set_index("symbol")
    if float(grid.loc["sh600001", "predicted_return_5d"]) >= float(grid.loc["sh600002", "predicted_return_5d"]):
        failures.append("negative-direction grid_trading was not inverted")
    if float(limit_up.loc["sh600002", "predicted_return_5d"]) <= float(limit_up.loc["sh600001", "predicted_return_5d"]):
        failures.append("positive-direction limit_up_follow was not preserved")
    if float(grid["reputation_weight"].iloc[0]) != float(GOVERNANCE_FACTOR_JUDGED_ALPHA_WEIGHTS["grid_trading"]):
        failures.append("grid_trading judged weight not applied")

    if failures:
        for failure in failures:
            print(f"[FAIL] {failure}")
        return 1
    print("[PASS] formal_defensive_bundle registered")
    print("[PASS] judged_core_bundle compatibility alias retained")
    print("[PASS] mainline variant uses factor_judged")
    print("[PASS] judged weights and direction handling applied")
    print(f"[PASS] runnable models: {', '.join(models)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
