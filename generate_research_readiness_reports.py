# -*- coding: utf-8 -*-
"""Write honest P0 readiness reports for the currently attached local sources."""
from __future__ import annotations

import json

import pandas as pd

from config import REPORT_DIR
from functions.governance import default_fallback_disclosures, research_status_dict


def generate_research_readiness_reports():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    feasibility_path = REPORT_DIR / "pit_data_source_feasibility_report.md"
    scorecard_path = REPORT_DIR / "corporate_action_source_scorecard.csv"
    decision_path = REPORT_DIR / "pit_formal_scope_decision.md"
    status_path = REPORT_DIR / "formal_readiness_status.json"

    feasibility_path.write_text(
        """# PIT Data Source Feasibility Report

## Decision

Full formal research is blocked for the currently attached local-data scope.

## Evidence

- TDX local `.day` files provide nominal daily OHLCV bars suitable for exploratory execution modeling.
- Provider adjustment-factor scaffolding exists, but local bars alone do not prove PIT factor observability.
- The attached corporate-action interface does not prove complete announcement date, record date, ex-date, payment date, rights-payment window, and revision timestamps.
- PIT universe membership, PIT industry classification, investable benchmark artifacts, and signed independent review are not attached.

## Threshold Policy

A future provider assessment must record the evidence for every threshold. A starting critical corporate-action missing-rate threshold may be 2%, but it is not approved for formal use until the governance owner records the justification and approval.

## Reassessment Triggers

- Purchase or replacement of a data source
- New PIT fields from a provider
- Coverage-period expansion
- Corporate-action revision-process change
- Annual scheduled review
- Governance-owner-approved special review
""",
        encoding="utf-8",
    )

    pd.DataFrame(
        [
            ("nominal_daily_prices", "tdx_local_day", "available", "Nominal OHLCV bars are available."),
            ("announcement_date", "corporate_action_provider", "unverified", "Required before formal PIT adjustment."),
            ("record_date", "corporate_action_provider", "unverified", "Required before formal corporate-action ledger."),
            ("ex_date", "corporate_action_provider", "unverified", "Required before formal PIT adjustment."),
            ("payment_date", "corporate_action_provider", "unverified", "Pending dividends cannot become available cash without it."),
            ("rights_payment_window", "corporate_action_provider", "unverified", "Required for rights-issue cash freezes."),
            ("revision_history", "corporate_action_provider", "unverified", "Required to audit revised events."),
            ("pit_universe", "universe_provider", "unverified", "Required to avoid survivorship bias."),
            ("pit_industry", "industry_provider", "unverified", "Required for industry-neutral formal strategies."),
        ],
        columns=["field", "source", "status", "reason"],
    ).to_csv(scorecard_path, index=False, encoding="utf-8-sig")

    disclosures = default_fallback_disclosures()
    decision_path.write_text(
        "# PIT Formal Scope Decision\n\n"
        "## Current Scope\n\n"
        "`formal` is blocked. The approved runnable fallback is "
        "`exploratory_after_p0_engine`.\n\n"
        "## Active Block Reasons\n\n"
        + "\n".join(f"- `{item.block_reason_code}`: {item.reason}" for item in disclosures)
        + "\n\n## Change Log\n\n"
        "- Initial local-data assessment: full formal scope blocked pending verified external PIT sources.\n",
        encoding="utf-8",
    )

    status_path.write_text(
        json.dumps(research_status_dict(), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return [feasibility_path, scorecard_path, decision_path, status_path]


if __name__ == "__main__":
    for output in generate_research_readiness_reports():
        print("Saved:", output)
