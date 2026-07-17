from __future__ import annotations

from types import MappingProxyType, SimpleNamespace

import pandas as pd

from functions.decision_council.cabinet_native_scoring import attach_cabinet_native_scores
from functions.decision_council.factor_semantic_contract import (
    build_factor_semantic_contracts,
    validate_factor_semantic_contracts,
)
from functions.decision_council.factor_source import (
    FACTOR_SOURCE_SELECTED_CABINET,
    resolve_factor_source,
)
from functions.decision_council.proposals import build_rule_alpha_proposals


RUN_ID = "pruned_run20260714_184846_581132_20260715_230524"


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def _synthetic_context():
    names = ("strict_a", "strict_a_relative", "proxy_value", "timing_rsi", "liquidity_flow")
    return SimpleNamespace(
        factor_source="selected_factor_cabinet",
        model_feature_map=MappingProxyType({name: f"cand_{name}" for name in names}),
        primary_role_map=MappingProxyType({
            "strict_a": "entry_alpha",
            "strict_a_relative": "entry_alpha",
            "proxy_value": "entry_alpha_proxy",
            "timing_rsi": "timing_filter",
            "liquidity_flow": "liquidity_filter",
        }),
        role_map=MappingProxyType({}),
        family_map=MappingProxyType({
            "strict_a": "size_a", "strict_a_relative": "size_b",
            "proxy_value": "valuation", "timing_rsi": "rsi", "liquidity_flow": "orderflow",
        }),
        module_map=MappingProxyType({
            "strict_a": "barra_style", "strict_a_relative": "barra_style",
            "proxy_value": "valuation", "timing_rsi": "rsi", "liquidity_flow": "flow_close",
        }),
        direction_map=MappingProxyType({name: "higher_better" for name in names}),
        near_relative_map=MappingProxyType({
            "strict_a": "size_relative", "strict_a_relative": "size_relative",
            "proxy_value": "value_relative", "timing_rsi": "rsi_relative", "liquidity_flow": "flow_relative",
        }),
        horizon_map=MappingProxyType({name: 5 for name in names}),
    )


def main() -> None:
    spec = resolve_factor_source(
        factor_source=FACTOR_SOURCE_SELECTED_CABINET,
        factor_cabinet_run_id=RUN_ID,
    )
    contracts = build_factor_semantic_contracts(spec.runtime_context())
    audit = validate_factor_semantic_contracts(contracts, expected_models=spec.alpha_models)
    _check(audit["contract_count"] == spec.factor_count == 74, "latest pruned cabinet has 74 semantic contracts")
    _check(audit["roles"].get("entry_alpha") == 6, "strict entry role remains distinct")
    _check(audit["roles"].get("entry_alpha_proxy") == 12, "proxy entry role remains distinct")

    context = _synthetic_context()
    candidates = pd.DataFrame({"symbol": ["A", "B", "C"]})
    proposals = pd.DataFrame([
        (symbol, model, score)
        for model, values in {
            "strict_a": (3.0, 2.0, 1.0),
            "strict_a_relative": (30.0, 20.0, 10.0),
            "proxy_value": (1.0, 3.0, 2.0),
            "timing_rsi": (3.0, 1.0, 2.0),
            "liquidity_flow": (2.0, 1.0, 3.0),
        }.items()
        for symbol, score in zip(("A", "B", "C"), values)
    ], columns=["symbol", "model_name", "predicted_return_5d"])
    scored, family = attach_cabinet_native_scores(candidates, proposals, runtime_context=context)
    _check(scored["cabinet_native_final_score"].between(0.0, 1.0).all(), "native scores are bounded")
    strict_family = family[(family["primary_role"] == "entry_alpha") & (family["economic_family"] == "size_style")]
    _check(len(strict_family) == 3, "two near-relative strict factors produce one family row per symbol")
    _check(scored["cabinet_strict_entry_score_coverage"].eq(1.0).all(), "configured strict family coverage is explicit")

    reduced = proposals[proposals["model_name"] != "strict_a_relative"]
    rescored, _ = attach_cabinet_native_scores(candidates, reduced, runtime_context=context)
    left = scored.set_index("symbol")["cabinet_strict_entry_score"].sort_index()
    right = rescored.set_index("symbol")["cabinet_strict_entry_score"].sort_index()
    _check(left.equals(right), "duplicating a near-relative factor does not increase its family vote")

    direction_context = SimpleNamespace(
        model_feature_map=MappingProxyType({"low_is_good": "cand_low_is_good"}),
        direction_map=MappingProxyType({"low_is_good": "lower_better"}),
    )
    directional = build_rule_alpha_proposals(
        pd.DataFrame({"symbol": ["A", "B"], "cand_low_is_good": [1.0, 3.0], "volatility_20": [0.02, 0.02]}),
        model_names=("low_is_good",),
        factor_judged=True,
        runtime_context=direction_context,
    )
    predicted = directional.set_index("symbol")["predicted_return_5d"]
    _check(predicted["A"] > predicted["B"], "cabinet-native lower_better direction reaches proposal scores")
    print("Cabinet-native semantic smoke complete.")


if __name__ == "__main__":
    main()
