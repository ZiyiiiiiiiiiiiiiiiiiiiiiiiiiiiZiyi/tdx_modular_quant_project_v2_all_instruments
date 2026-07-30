"""Verify point-in-time empirical factor clustering prevents repeated votes."""
from __future__ import annotations

from types import MappingProxyType, SimpleNamespace

import pandas as pd

from functions.decision_council.cabinet_native_scoring import (
    attach_cabinet_native_scores,
)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


models = ("trend_a", "trend_duplicate", "independent_value")
context = SimpleNamespace(
    factor_source="selected_factor_cabinet",
    model_feature_map=MappingProxyType({model: f"cand_{model}" for model in models}),
    primary_role_map=MappingProxyType({model: "entry_alpha" for model in models}),
    role_map=MappingProxyType({}),
    family_map=MappingProxyType(
        {
            "trend_a": "momentum",
            "trend_duplicate": "valuation",
            "independent_value": "quality",
        }
    ),
    module_map=MappingProxyType(
        {
            "trend_a": "trend",
            "trend_duplicate": "valuation",
            "independent_value": "quality",
        }
    ),
    direction_map=MappingProxyType({model: "higher_better" for model in models}),
    near_relative_map=MappingProxyType(
        {
            "trend_a": "trend_a_unique",
            "trend_duplicate": "trend_duplicate_unique",
            "independent_value": "independent_value_unique",
        }
    ),
    horizon_map=MappingProxyType({model: 5 for model in models}),
)
symbols = [f"s{index:02d}" for index in range(40)]
independent_order = [
    17, 3, 31, 8, 22, 0, 36, 12, 27, 5,
    19, 34, 10, 25, 1, 38, 14, 29, 7, 21,
    33, 4, 16, 30, 9, 24, 2, 37, 13, 28,
    6, 20, 35, 11, 26, 18, 32, 15, 39, 23,
]
rows = []
for index, symbol in enumerate(symbols):
    rows.extend(
        [
            (symbol, "trend_a", float(index)),
            (symbol, "trend_duplicate", float(index) * 10.0 + 7.0),
            (symbol, "independent_value", float(independent_order[index])),
        ]
    )
proposals = pd.DataFrame(
    rows, columns=["symbol", "model_name", "predicted_return_5d"]
)
candidates = pd.DataFrame({"symbol": symbols})
scored, _ = attach_cabinet_native_scores(
    candidates,
    proposals,
    runtime_context=context,
    empirical_cluster_threshold=0.90,
    empirical_cluster_min_observations=30,
)
check(
    int(scored["cabinet_raw_factor_count"].iloc[0]) == 3,
    "raw factor count remains auditable",
)
check(
    int(scored["cabinet_empirical_cluster_count"].iloc[0]) == 2,
    "perfect cross-family duplicate factors collapse into one empirical cluster",
)

reduced, _ = attach_cabinet_native_scores(
    candidates,
    proposals[proposals["model_name"] != "trend_duplicate"],
    runtime_context=context,
    empirical_cluster_threshold=0.90,
    empirical_cluster_min_observations=30,
)
left = scored.set_index("symbol")["cabinet_native_final_score"].sort_index()
right = reduced.set_index("symbol")["cabinet_native_final_score"].sort_index()
check(
    left.equals(right),
    "removing an empirically duplicate factor does not change its voting power",
)
print("Empirical factor cluster contract verification passed.")
