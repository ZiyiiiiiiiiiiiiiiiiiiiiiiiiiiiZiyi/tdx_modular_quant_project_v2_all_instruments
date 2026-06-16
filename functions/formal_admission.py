# -*- coding: utf-8 -*-
"""Automatic binary formal-admission audit."""
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
from functions.data_integrity import build_data_integrity_report, data_verified


def build_formal_admission_report() -> pd.DataFrame:
    integrity = build_data_integrity_report()
    rows = [
        _artifact_gate("governance_covenant", "RESEARCH_GOVERNANCE.md", FormalBlockReason.GOVERNANCE_NOT_SIGNED),
        _artifact_gate("pit_adjustment_artifact", ADJUSTMENT_FACTORS_PARQUET, FormalBlockReason.PIT_ADJUSTMENT_UNVERIFIED),
        _artifact_gate("corporate_action_artifact", CORPORATE_ACTIONS_PARQUET, FormalBlockReason.PIT_CORPORATE_ACTION_UNVERIFIED),
        _artifact_gate("feature_lineage", FEATURE_LINEAGE_CSV, FormalBlockReason.LINEAGE_COVERAGE_LOW),
        _integrity_gate(
            integrity,
            "feature_timestamp_audit",
            fallback_path=FEATURE_TIMESTAMP_AUDIT_CSV,
            failure_reason=FormalBlockReason.FEATURE_TIMESTAMP_AUDIT_FAILED,
        ),
        _integrity_gate(
            integrity,
            "investable_benchmark",
            fallback_path=BENCHMARK_REPORT_CSV,
            failure_reason=FormalBlockReason.BENCHMARK_NOT_INVESTABLE,
            report_gate_name="benchmark_report",
        ),
        _artifact_gate("reproducibility_manifest", FORMAL_MANIFEST_JSON, FormalBlockReason.REPRO_PACKAGE_MISSING),
        {
            "gate": "test_lock_enabled",
            "status": "passed" if TEST_LOCK_ENABLED else "failed",
            "formal_block_reason_code": "" if TEST_LOCK_ENABLED else FormalBlockReason.POST_TEST_CONTAMINATED.value,
            "detail": f"TEST_LOCK_ENABLED={TEST_LOCK_ENABLED}",
        },
    ]
    rows.append(
        {
            "gate": "v6_data_verified",
            "status": "passed" if data_verified(integrity) else "failed",
            "formal_block_reason_code": "" if data_verified(integrity) else FormalBlockReason.PIT_UNIVERSE_UNVERIFIED.value,
            "detail": "All objective V6 data-integrity gates must pass.",
        }
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


def _artifact_gate(gate, path, reason):
    exists = Path(path).exists()
    status = "passed" if exists else "failed"
    return {
        "gate": gate,
        "status": status,
        "formal_block_reason_code": "" if status == "passed" else reason.value,
        "detail": str(path),
    }


def _integrity_gate(
    integrity_report: pd.DataFrame,
    integrity_gate_name: str,
    *,
    fallback_path,
    failure_reason,
    report_gate_name: str | None = None,
):
    gate_name = report_gate_name or integrity_gate_name
    if integrity_report is not None and not integrity_report.empty and "gate" in integrity_report.columns:
        matched = integrity_report[integrity_report["gate"].astype(str) == str(integrity_gate_name)]
        if not matched.empty:
            row = matched.iloc[0]
            passed = bool(row.get("passed"))
            detail = str(row.get("detail", fallback_path))
            return {
                "gate": gate_name,
                "status": "passed" if passed else "failed",
                "formal_block_reason_code": "" if passed else failure_reason.value,
                "detail": detail,
            }
    return _artifact_gate(gate_name, fallback_path, failure_reason)
