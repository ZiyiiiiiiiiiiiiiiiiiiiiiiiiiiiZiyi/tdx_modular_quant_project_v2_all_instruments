"""V6 data-integrity gates and non-bypassable research status."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from config import (
    ADJUSTMENT_FACTORS_PARQUET,
    ADJUSTMENT_PTI_QUALITY_CSV,
    BENCHMARK_REPORT_CSV,
    CORPORATE_ACTIONS_PARQUET,
    CORPORATE_ACTIONS_QUALITY_CSV,
    DATA_INTEGRITY_REPORT_CSV,
    DATA_INTEGRITY_WHITEPAPER_MD,
    DATA_VERIFICATION_STATUS_JSON,
    FEATURE_LINEAGE_CSV,
    FEATURE_TIMESTAMP_AUDIT_CSV,
    FORMAL_MANIFEST_JSON,
    PROCESSED_DIR,
    START_DATE,
    STRATEGY_END_DATE,
    V6_RESEARCH_WATERMARK,
)


@dataclass(frozen=True)
class DataGate:
    gate: str
    required: bool
    passed: bool
    detail: str
    artifact: str


def build_data_integrity_report() -> pd.DataFrame:
    """Return objective gates only; artifact existence alone is not verification."""
    index_path = PROCESSED_DIR / "index_constituents.parquet"
    gates = [
        _file_gate("adjustment_factors", ADJUSTMENT_FACTORS_PARQUET),
        _csv_status_gate("adjustment_pti_audit", ADJUSTMENT_PTI_QUALITY_CSV),
        _file_gate("corporate_actions", CORPORATE_ACTIONS_PARQUET),
        _csv_status_gate("corporate_actions_quality", CORPORATE_ACTIONS_QUALITY_CSV),
        _csv_status_gate("feature_timestamp_audit", FEATURE_TIMESTAMP_AUDIT_CSV),
        _file_gate("feature_lineage", FEATURE_LINEAGE_CSV),
        _csv_status_gate("investable_benchmark", BENCHMARK_REPORT_CSV),
        _file_gate("reproducibility_manifest", FORMAL_MANIFEST_JSON),
        _index_gate(index_path),
    ]
    return pd.DataFrame([asdict(gate) for gate in gates])


def data_verified(report: pd.DataFrame | None = None) -> bool:
    report = build_data_integrity_report() if report is None else report
    required = report[report["required"].astype(bool)]
    return bool(not required.empty and required["passed"].astype(bool).all())


def save_data_integrity_artifacts() -> tuple[Path, Path, Path]:
    report = build_data_integrity_report()
    DATA_INTEGRITY_REPORT_CSV.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(DATA_INTEGRITY_REPORT_CSV, index=False, encoding="utf-8-sig")
    verified = data_verified(report)
    status = {
        "data_verified": verified,
        "formal_admission_allowed": verified,
        "watermark_required": not verified,
        "watermark": "" if verified else V6_RESEARCH_WATERMARK,
        "failed_gates": report.loc[~report["passed"].astype(bool), "gate"].tolist(),
    }
    DATA_VERIFICATION_STATUS_JSON.write_text(
        json.dumps(status, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# 数据完整性白皮书",
        "",
        f"- data_verified: `{verified}`",
        f"- 正式准入允许: `{verified}`",
        f"- 研究水印: `{status['watermark']}`",
        "",
        "## 门禁结果",
        "",
        "| 门禁 | 必需 | 通过 | 说明 |",
        "|---|---:|---:|---|",
    ]
    for row in report.to_dict("records"):
        lines.append(
            f"| {row['gate']} | {row['required']} | {row['passed']} | "
            f"{str(row['detail']).replace('|', '/')} |"
        )
    DATA_INTEGRITY_WHITEPAPER_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return DATA_INTEGRITY_REPORT_CSV, DATA_VERIFICATION_STATUS_JSON, DATA_INTEGRITY_WHITEPAPER_MD


def research_watermark(report: pd.DataFrame | None = None) -> str:
    return "" if data_verified(report) else V6_RESEARCH_WATERMARK


def _file_gate(name: str, path) -> DataGate:
    artifact = Path(path)
    passed = artifact.exists() and artifact.stat().st_size > 0
    return DataGate(name, True, passed, "artifact exists and is non-empty", str(artifact))


def _csv_status_gate(name: str, path) -> DataGate:
    artifact = Path(path)
    if not artifact.exists() or artifact.stat().st_size == 0:
        return DataGate(name, True, False, "artifact missing", str(artifact))
    try:
        frame = pd.read_csv(artifact)
    except Exception as exc:
        return DataGate(name, True, False, f"cannot read artifact: {exc}", str(artifact))
    if frame.empty:
        return DataGate(name, True, False, "artifact is empty", str(artifact))
    status_columns = [column for column in frame.columns if "status" in column.lower()]
    if not status_columns:
        return DataGate(name, True, False, "no auditable status column", str(artifact))
    values = {
        str(value).strip().lower()
        for column in status_columns
        for value in frame[column].dropna().tolist()
    }
    failed = any(
        value
        in {
            "failed",
            "fail",
            "unverified",
            "blocked",
            "coverage_gap",
            "manual_review_required",
        }
        for value in values
    )
    passed = bool(values) and not failed
    return DataGate(name, True, passed, f"status_values={sorted(values)}", str(artifact))


def _index_gate(path: Path) -> DataGate:
    if not path.exists() or path.stat().st_size == 0:
        return DataGate("pit_index_constituents", True, False, "artifact missing", str(path))
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        return DataGate("pit_index_constituents", True, False, f"cannot read artifact: {exc}", str(path))
    required = {"index_code", "symbol"}
    if not required.issubset(frame.columns):
        return DataGate("pit_index_constituents", True, False, "required columns missing", str(path))
    date_columns = {"effective_date", "first_trade_date"} & set(frame.columns)
    codes = set(frame["index_code"].astype(str).str.replace(".SH", "", regex=False))
    expected = {"000300", "000905", "000510"}
    start_column = "effective_date" if "effective_date" in frame.columns else "first_trade_date"
    frame[start_column] = pd.to_datetime(frame[start_column], errors="coerce")
    frame["out_date"] = pd.to_datetime(
        frame.get("out_date", pd.Series(pd.NaT, index=frame.index)),
        errors="coerce",
    ).fillna(pd.Timestamp.max.normalize())
    coverage = {}
    start = pd.Timestamp(START_DATE)
    end = pd.Timestamp(STRATEGY_END_DATE or pd.Timestamp.today().normalize())
    for code in expected:
        members = frame[frame["index_code"].astype(str).str.replace(".SH", "", regex=False) == code]
        coverage[code] = bool(
            not members.empty
            and (members[start_column] <= start).any()
            and (members["out_date"] > end).any()
        )
    source_values = set(frame.get("source", pd.Series(dtype=str)).dropna().astype(str).str.lower())
    static_only = bool(source_values) and all(
        "current" in value or "snapshot" in value for value in source_values
    )
    passed = (
        bool(date_columns)
        and expected.issubset(codes)
        and all(coverage.values())
        and not static_only
    )
    detail = (
        f"date_columns={sorted(date_columns)}, index_codes={sorted(codes)}, "
        f"coverage={coverage}, static_only={static_only}, period={start.date()}..{end.date()}"
    )
    return DataGate("pit_index_constituents", True, passed, detail, str(path))
