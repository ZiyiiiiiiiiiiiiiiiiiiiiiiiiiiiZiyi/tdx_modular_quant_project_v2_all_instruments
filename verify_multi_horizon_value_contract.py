from __future__ import annotations

import pandas as pd

from functions.decision_council.multi_horizon_value import (
    attach_multi_horizon_value_contract,
    comparable_pair,
)


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> int:
    source = pd.DataFrame([
        {"symbol": "holding", "entry_matrix_score": 0.10, "expected_edge_10d": 0.012, "conservative_expected_edge_10d": 0.004},
        {"symbol": "challenger", "entry_matrix_score": 0.99, "expected_edge_10d": 0.018, "conservative_expected_edge_10d": 0.007},
        {"symbol": "rank_only", "entry_matrix_score": 0.999},
        {"symbol": "five_only", "expected_edge_5d": 0.006, "conservative_expected_edge_5d": 0.001},
        {"symbol": "medium_authorized", "expected_edge_10d": 0.01, "conservative_expected_edge_10d": 0.002,
         "expected_edge_20d": 0.03, "conservative_expected_edge_20d": 0.01,
         "ml_medium_value_authorized": True, "replacement_value_preferred_horizon_days": 20},
        {"symbol": "medium_paper", "expected_edge_10d": 0.01, "conservative_expected_edge_10d": 0.002,
         "expected_edge_20d": 0.03, "conservative_expected_edge_20d": 0.01,
         "ml_medium_value_authorized": False, "replacement_value_preferred_horizon_days": 20},
    ])
    out = attach_multi_horizon_value_contract(source).set_index("symbol")
    expect(abs(float(out.at["challenger", "comparable_expected_alpha"]) - 0.018) < 1e-12,
           "comparable value remains in return units")
    expect(not bool(out.at["rank_only", "comparable_value_available"]),
           "an ordinal ranking score cannot silently become an expected return")
    expect(int(out.at["five_only", "comparable_value_horizon_days"]) == 5,
           "an independently calibrated five-day forecast keeps its own horizon")
    expect(comparable_pair(out.loc["holding"], out.loc["challenger"]),
           "holding and challenger are comparable when the bounded horizon matches")
    expect(not comparable_pair(out.loc["holding"], out.loc["five_only"]),
           "different forecast horizons cannot be subtracted")
    expect(pd.isna(out.at["holding", "expected_alpha_20d"]),
           "missing twenty-day evidence remains unavailable rather than extrapolated")
    expect(int(out.at["medium_authorized", "comparable_value_horizon_days"]) == 20,
           "authorized medium ML owns replacement value")
    expect(int(out.at["medium_paper", "comparable_value_horizon_days"]) == 10,
           "unauthorized medium ML remains paper-only behind the rule horizon")
    print("[PASS] multi-horizon value contract verification completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
