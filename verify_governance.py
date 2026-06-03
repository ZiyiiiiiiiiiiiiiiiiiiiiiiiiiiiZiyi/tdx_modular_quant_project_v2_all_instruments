# -*- coding: utf-8 -*-
from functions.governance import (
    FormalBlockReason,
    FormalStatus,
    build_research_status,
    default_fallback_disclosures,
    resolve_formal_status,
)


def verify_governance():
    status = build_research_status()
    disclosures = default_fallback_disclosures()
    assert FormalStatus.EXPLORATORY_AFTER_P0_ENGINE.value == status.formal_status
    assert status.formal_eligible is False
    assert disclosures
    assert FormalBlockReason.PIT_CORPORATE_ACTION_UNVERIFIED.value in status.formal_block_reason_code
    assert FormalBlockReason.ACCOUNT_LEDGER_INCOMPLETE.value in status.formal_block_reason_code
    assert resolve_formal_status([FormalBlockReason.PIT_ADJUSTMENT_UNVERIFIED.value]) == "formal_blocked"
    assert resolve_formal_status([], limited_independence=True) == "formal_candidate_limited"
    assert resolve_formal_status([], post_test_modified=True) == "formal_contaminated"
    print("Governance verification passed.")
    print("Fallback disclosures:", len(disclosures))


if __name__ == "__main__":
    verify_governance()
