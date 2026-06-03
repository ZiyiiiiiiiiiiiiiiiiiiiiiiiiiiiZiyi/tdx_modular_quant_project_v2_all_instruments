# -*- coding: utf-8 -*-
"""Automatic formal-admission audit. Manual review remains mandatory."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from config import (
    ADJUSTMENT_FACTORS_PARQUET,
    BENCHMARK_REPORT_CSV,
    CORPORATE_ACTIONS_PARQUET,
    FEATURE_LINEAGE_CSV,
    FEATURE_TIMESTAMP_AUDIT_CSV,
    FORMAL_ADMISSION_REPORT_CSV,
    FORMAL_MANIFEST_JSON,
    TEST_LOCK_ENABLED,
)
from functions.governance import FormalBlockReason


def build_formal_admission_report() -> pd.DataFrame:
    rows = [
        _artifact_gate("governance_covenant", "RESEARCH_GOVERNANCE.md", FormalBlockReason.GOVERNANCE_NOT_SIGNED),
        _artifact_gate("pit_adjustment_artifact", ADJUSTMENT_FACTORS_PARQUET, FormalBlockReason.PIT_ADJUSTMENT_UNVERIFIED, manual=True),
        _artifact_gate("corporate_action_artifact", CORPORATE_ACTIONS_PARQUET, FormalBlockReason.PIT_CORPORATE_ACTION_UNVERIFIED, manual=True),
        _artifact_gate("feature_lineage", FEATURE_LINEAGE_CSV, FormalBlockReason.LINEAGE_COVERAGE_LOW),
        _artifact_gate("feature_timestamp_audit", FEATURE_TIMESTAMP_AUDIT_CSV, FormalBlockReason.FEATURE_TIMESTAMP_AUDIT_FAILED),
        _artifact_gate("benchmark_report", BENCHMARK_REPORT_CSV, FormalBlockReason.BENCHMARK_NOT_INVESTABLE, manual=True),
        _artifact_gate("reproducibility_manifest", FORMAL_MANIFEST_JSON, FormalBlockReason.REPRO_PACKAGE_MISSING, manual=True),
        {
            "gate": "test_lock_enabled",
            "status": "passed" if TEST_LOCK_ENABLED else "failed",
            "formal_block_reason_code": "" if TEST_LOCK_ENABLED else FormalBlockReason.POST_TEST_CONTAMINATED.value,
            "detail": f"TEST_LOCK_ENABLED={TEST_LOCK_ENABLED}",
        },
    ]
    rows.extend(
        [
            _manual_gate("pit_universe_review", FormalBlockReason.PIT_UNIVERSE_UNVERIFIED),
            _manual_gate("pit_industry_review", FormalBlockReason.PIT_INDUSTRY_UNVERIFIED),
            _manual_gate("account_ledger_integration", FormalBlockReason.ACCOUNT_LEDGER_INCOMPLETE),
            _manual_gate("tax_ledger_integration", FormalBlockReason.TAX_LEDGER_MISSING),
            _manual_gate("independent_manual_review", FormalBlockReason.LIMITED_REVIEW_INDEPENDENCE),
        ]
    )
    return pd.DataFrame(rows)


def save_formal_admission_report(output_path=FORMAL_ADMISSION_REPORT_CSV):
    report = build_formal_admission_report()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(output_path, index=False, encoding="utf-8-sig")
    return Path(output_path)


def formal_admission_passed(report=None):
    report = report if report is not None else build_formal_admission_report()
    return bool(not report.empty and (report["status"] == "passed").all())


def _artifact_gate(gate, path, reason, manual=False):
    exists = Path(path).exists()
    if exists and manual:
        status = "manual_review_required"
    else:
        status = "passed" if exists else "failed"
    return {
        "gate": gate,
        "status": status,
        "formal_block_reason_code": "" if status == "passed" else reason.value,
        "detail": str(path),
    }


def _manual_gate(gate, reason):
    return {
        "gate": gate,
        "status": "manual_review_required",
        "formal_block_reason_code": reason.value,
        "detail": "Requires verified provider data or independent manual sign-off.",
    }
