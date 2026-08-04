"""Verify strict held-symbol-day factor coverage semantics."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.holding_factor_products import (
    classify_holding_factor_coverage,
    workbook_content_check_failures,
)


def _classify(observed: int, **state) -> pd.Series:
    keys = pd.DataFrame([{"date": "2026-01-05", "symbol": "sz000001"}])
    counts = pd.DataFrame(
        [
            {
                "date": "2026-01-05",
                "symbol": "sz000001",
                "observed_factor_count": observed,
            }
        ]
    )
    base = {
        "date": "2026-01-05",
        "symbol": "sz000001",
        "position_state": "held",
        "state_observation_status": "observed_current_feature",
        "state_source_date": "2026-01-05",
        "valuation_source": "current_close",
        "stale_days": 0,
    }
    base.update(state)
    return classify_holding_factor_coverage(
        keys,
        counts,
        pd.DataFrame([base]),
        expected_factor_count=74,
    ).iloc[0]


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"[PASS] {name}")


def main() -> int:
    complete = _classify(74)
    check("observable 74-of-74 passes", complete["coverage_status"] == "complete")
    check("observable 74-of-74 is complete", bool(complete["coverage_complete"]))

    unobserved = _classify(
        0,
        position_state="held_unobserved",
        state_observation_status="carried_forward_missing_current_feature",
        state_source_date="2026-01-02",
        valuation_source="last_known_close",
        stale_days=1,
    )
    check(
        "persisted unobserved holding passes with disclosure",
        unobserved["coverage_status"] == "justified_unobserved_holding"
        and bool(unobserved["coverage_gate_passed"]),
    )
    check(
        "unobserved holding never pretends factor completeness",
        not bool(unobserved["coverage_complete"]),
    )

    missing = _classify(0)
    check(
        "observable no-factor record fails",
        missing["coverage_status"] == "unexpected_no_factor_record"
        and bool(missing["coverage_gate_failure"]),
    )
    partial = _classify(73)
    check(
        "observable partial factor record fails",
        partial["coverage_status"] == "unexpected_partial_factor_record"
        and bool(partial["coverage_gate_failure"]),
    )
    false_label = _classify(
        0,
        position_state="held_unobserved",
        state_observation_status="observed_current_feature",
        valuation_source="last_known_close",
        stale_days=1,
    )
    check(
        "held_unobserved label alone cannot bypass gate",
        bool(false_label["coverage_gate_failure"]),
    )
    stale_factors = _classify(
        74,
        position_state="held_unobserved",
        state_observation_status="carried_forward_missing_current_feature",
        state_source_date="2026-01-02",
        valuation_source="last_known_close",
        stale_days=1,
    )
    check(
        "filled factor records fail instead of hiding unobserved market state",
        not bool(stale_factors["market_observed"])
        and stale_factors["coverage_status"]
        == "unexpected_factor_record_for_unobserved_holding"
        and bool(stale_factors["coverage_gate_failure"]),
    )
    check(
        "content gate ignores disclosed unobserved count",
        not workbook_content_check_failures(
            {
                "holding_symbol_days": 10,
                "covered_holding_symbol_days": 10,
                "unexpected_holding_factor_coverage_gap_count": 0,
                "held_symbol_count": 1,
                "factor_model_count": 74,
            }
        ),
    )
    check(
        "content gate rejects unexpected gap",
        workbook_content_check_failures(
            {
                "unexpected_holding_factor_coverage_gap_count": 1,
                "held_symbol_count": 1,
                "factor_model_count": 74,
            }
        )
        == ["holding_symbol_day_factor_coverage"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
