# -*- coding: utf-8 -*-
"""Verify formal admission uses audited gate status, not artifact existence alone."""
from __future__ import annotations

from functions.formal_admission import build_formal_admission_report


def verify_formal_admission_alignment():
    print("=== Verify formal admission alignment ===")
    report = build_formal_admission_report()
    _expect(not report.empty, "formal admission report should not be empty")

    benchmark = report[report["gate"].astype(str) == "benchmark_report"]
    _expect(not benchmark.empty, "benchmark gate should exist")
    _expect(
        str(benchmark.iloc[0]["status"]) == "failed",
        "benchmark gate should fail until audited benchmark status is fully passed",
    )

    timestamp = report[report["gate"].astype(str) == "feature_timestamp_audit"]
    _expect(not timestamp.empty, "feature timestamp gate should exist")
    _expect(
        str(timestamp.iloc[0]["status"]) == "failed",
        "feature timestamp gate should respect audited status values",
    )
    print("Formal admission alignment verification passed.")


def _expect(condition, message):
    if not condition:
        raise SystemExit(message)
    print(f"[PASS] {message}")


if __name__ == "__main__":
    verify_formal_admission_alignment()
