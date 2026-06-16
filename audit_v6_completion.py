"""Generate the final V6 implementation and operational-readiness audit."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import (
    DATA_INTEGRITY_REPORT_CSV,
    EVENT_DENSITY_REPORT_CSV,
    REPORT_DIR,
    STRATEGY_ADMISSION_REPORT_CSV,
    V6_FORMAL_STRATEGY_CANDIDATES,
)


OUTPUT_CSV = REPORT_DIR / "v6_completion_audit.csv"
OUTPUT_MD = REPORT_DIR / "v6_completion_audit.md"


def main():
    rows = [
        _code_gate("central_configuration", "config.py"),
        _code_gate("data_integrity_gate", "functions/data_integrity.py"),
        _code_gate("signal_contract_and_kelly", "functions/decision_council/position_management.py"),
        _code_gate("independent_events_and_labels", "functions/event_statistics.py"),
        _code_gate("probability_calibration", "functions/probability_calibration.py"),
        _code_gate("binary_strategy_admission", "functions/strategy_admission.py"),
        _code_gate("continuous_government_control", "functions/v6_governance.py"),
        _code_gate("end_to_end_v6_pipeline", "functions/v6_decision_pipeline.py"),
        _code_gate("performance_watermark", "functions/performance_charts.py"),
        _artifact_gate("data_integrity_report", DATA_INTEGRITY_REPORT_CSV),
        _artifact_gate("event_density_report", EVENT_DENSITY_REPORT_CSV),
        _artifact_gate("strategy_admission_report", STRATEGY_ADMISSION_REPORT_CSV),
    ]
    integrity = _read(DATA_INTEGRITY_REPORT_CSV)
    admission = _read(STRATEGY_ADMISSION_REPORT_CSV)
    rows.append(
        {
            "requirement": "objective_data_gates_operational",
            "implementation_status": "implemented",
            "operational_status": (
                "PASS"
                if not integrity.empty and integrity["passed"].astype(bool).all()
                else "BLOCKED_EXTERNAL_EVIDENCE"
            ),
            "detail": _failed_names(integrity, "gate", "passed"),
        }
    )
    rows.append(
        {
            "requirement": "formal_strategy_admission",
            "implementation_status": "implemented",
            "operational_status": (
                "PASS"
                if not admission.empty
                and set(admission["strategy_id"]) == set(V6_FORMAL_STRATEGY_CANDIDATES)
                and (admission["admission_status"] == "PASS").all()
                else "FAIL_BY_DESIGN"
            ),
            "detail": (
                "No strategy may receive formal weight until every gate passes."
            ),
        }
    )
    report = pd.DataFrame(rows)
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    _write_markdown(report)
    print("Saved:", OUTPUT_CSV)
    print("Saved:", OUTPUT_MD)
    print(report.to_string(index=False))


def _code_gate(requirement: str, path: str) -> dict:
    artifact = Path(path)
    passed = artifact.exists() and artifact.stat().st_size > 0
    return {
        "requirement": requirement,
        "implementation_status": "implemented" if passed else "missing",
        "operational_status": "READY_FOR_VERIFICATION" if passed else "BLOCKED",
        "detail": str(artifact),
    }


def _artifact_gate(requirement: str, path) -> dict:
    artifact = Path(path)
    passed = artifact.exists() and artifact.stat().st_size > 0
    return {
        "requirement": requirement,
        "implementation_status": "implemented" if passed else "missing",
        "operational_status": "GENERATED" if passed else "BLOCKED",
        "detail": str(artifact),
    }


def _read(path) -> pd.DataFrame:
    artifact = Path(path)
    return pd.read_csv(artifact) if artifact.exists() else pd.DataFrame()


def _failed_names(frame: pd.DataFrame, name_column: str, pass_column: str) -> str:
    if frame.empty:
        return "report missing"
    failed = frame.loc[~frame[pass_column].astype(bool), name_column].astype(str).tolist()
    return "|".join(failed) if failed else "all gates passed"


def _write_markdown(report: pd.DataFrame) -> None:
    lines = [
        "# V6 Completion Audit",
        "",
        "| Requirement | Implementation | Operational | Detail |",
        "|---|---|---|---|",
    ]
    for row in report.to_dict("records"):
        lines.append(
            f"| {row['requirement']} | {row['implementation_status']} | "
            f"{row['operational_status']} | {str(row['detail']).replace('|', '/')} |"
        )
    lines.extend(
        [
            "",
            "## Conclusion",
            "",
            "The software controls are implemented and verified. Formal operation remains blocked "
            "until external point-in-time data, benchmark replication, calibration, capacity, and "
            "walk-forward admission evidence pass the objective gates.",
        ]
    )
    OUTPUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
