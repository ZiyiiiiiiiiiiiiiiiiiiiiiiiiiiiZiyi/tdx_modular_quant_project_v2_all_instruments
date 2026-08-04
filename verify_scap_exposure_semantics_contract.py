"""Focused verification for immutable exposure and holding semantics."""
from functions.decision_council.exposure_contract import (
    build_exposure_semantics,
    build_holding_semantics,
    build_record_lineage,
)


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print(f"[PASS] {name}")


def main():
    empty_candidate = build_exposure_semantics(
        strategic_target=0.75,
        strategic_lower_bound=0.60,
        strategic_upper_bound=0.85,
        hard_risk_ceiling=0.90,
        attainable_ceiling=0.40,
        optimizer_planned=0.40,
        actual=0.40,
    )
    check("candidate rejection cannot erase strategic gap", abs(empty_candidate.strategic_exposure_gap - 0.35) < 1e-12)
    check("attainable gap remains separately factual", empty_candidate.attainable_exposure_gap == 0.0)
    check("execution gap remains separately factual", empty_candidate.execution_exposure_gap == 0.0)

    holdings = build_holding_semantics(
        minimum_required=3,
        soft_target=4,
        maximum_allowed=5,
        optimizer_planned=1,
        actual=1,
    )
    check("ActionPlan cannot rewrite strategic holding target", holdings.soft_target_holding_count == 4)
    check("strategic holding shortage survives no-buy plan", holdings.strategic_holding_shortfall_count == 3)
    check("execution holding shortage is independent", holdings.execution_holding_shortfall_count == 0)
    grandfathered = build_holding_semantics(
        minimum_required=3,
        soft_target=4,
        maximum_allowed=5,
        optimizer_planned=6,
        actual=6,
    )
    check("grandfathered excess is disclosed, not rewritten", grandfathered.actual_excess_holding_count == 1)

    payload = {"symbol": "000001", "net_value": 12.5}
    first = build_record_lineage(
        decision_id="d1",
        record_stage="candidate_economic_assessment",
        record_id="p1",
        immutable_payload=payload,
        formula_version="v1",
    )
    repeat = build_record_lineage(
        decision_id="d1",
        record_stage="candidate_economic_assessment",
        record_id="p1",
        immutable_payload=payload,
        formula_version="v1",
    )
    correction = build_record_lineage(
        decision_id="d1",
        record_stage="candidate_economic_assessment",
        record_id="p1-c1",
        immutable_payload={**payload, "net_value": 13.0},
        formula_version="v2",
        supersedes_event_id=first["event_id"],
    )
    check("identical facts produce stable event id", first["event_id"] == repeat["event_id"])
    check("correction appends a new event", correction["event_id"] != first["event_id"])
    check("correction explicitly references original", correction["supersedes_event_id"] == first["event_id"])


if __name__ == "__main__":
    main()
