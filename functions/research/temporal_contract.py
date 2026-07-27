"""Fail-closed temporal isolation and recursive research-artifact lineage."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable

import pandas as pd


TEMPORAL_CONTRACT_VERSION = "factor_temporal_isolation_v1"
DATE_END_KEYS = (
    "factor_discovery_end", "analysis_end_date", "analysis_end",
    "training_end_date", "training_end", "validation_end_date", "validation_end",
    "role_calibration_end",
)
LINEAGE_PATH_KEYS = (
    "source_factor_cabinet_path", "base_factor_cabinet_path", "factor_cabinet_path",
    "appeal_source_path", "v1_run_dir", "source_run_dir",
)


@dataclass(frozen=True)
class TemporalEvidence:
    artifact_path: str
    artifact_hash: str
    evidence_key: str
    evidence_date: str
    source_kind: str


def validate_temporal_order(
    *,
    factor_discovery_end,
    role_calibration_end,
    oos_start,
) -> dict:
    """Require discovery < calibration < OOS, with strict date boundaries."""
    discovery = _date(factor_discovery_end, "factor_discovery_end")
    calibration = _date(role_calibration_end, "role_calibration_end")
    test = _date(oos_start, "oos_start")
    failures = []
    if discovery >= calibration:
        failures.append("factor_discovery_end_must_precede_role_calibration_end")
    if calibration >= test:
        failures.append("role_calibration_end_must_precede_oos_start")
    return {
        "contract_version": TEMPORAL_CONTRACT_VERSION,
        "factor_discovery_end": discovery.strftime("%Y-%m-%d"),
        "role_calibration_end": calibration.strftime("%Y-%m-%d"),
        "oos_start": test.strftime("%Y-%m-%d"),
        "temporal_isolation_pass": not failures,
        "failures": failures,
    }


def audit_artifact_lineage(
    artifact_path: str | Path,
    *,
    oos_start,
    extra_manifest_paths: Iterable[str | Path] = (),
) -> tuple[pd.DataFrame, dict]:
    """Recursively inspect manifest dates and fail when evidence is absent or overlaps OOS.

    The audit never assumes that a recently-created cabinet is OOS-safe.  It
    follows declared source paths and nearby manifest files, including the
    CSV manifest emitted by the fast factor judge.
    """
    root = Path(artifact_path)
    test = _date(oos_start, "oos_start")
    queue = [root, *(Path(item) for item in extra_manifest_paths)]
    visited: set[str] = set()
    evidence: list[TemporalEvidence] = []
    artifacts: list[Path] = []
    while queue:
        current = queue.pop(0)
        resolved = _resolve_existing(current)
        if resolved is None:
            continue
        key = str(resolved.resolve()).lower()
        if key in visited:
            continue
        visited.add(key)
        candidates = _manifest_candidates(resolved)
        for candidate in candidates:
            candidate_key = str(candidate.resolve()).lower()
            if candidate_key in visited and candidate != resolved:
                continue
            payloads = _read_payloads(candidate)
            if not payloads:
                continue
            artifacts.append(candidate)
            for payload, source_kind in payloads:
                for date_key in DATE_END_KEYS:
                    if date_key in payload and _optional_date(payload.get(date_key)) is not None:
                        value = _optional_date(payload[date_key])
                        evidence.append(TemporalEvidence(
                            artifact_path=str(candidate),
                            artifact_hash=_sha256(candidate),
                            evidence_key=date_key,
                            evidence_date=value.strftime("%Y-%m-%d"),
                            source_kind=source_kind,
                        ))
                for path_key in LINEAGE_PATH_KEYS:
                    linked = payload.get(path_key)
                    if linked:
                        linked_path = _path_from_payload(linked, candidate.parent)
                        queue.append(linked_path)
                for linked in payload.get("source_run_dirs", []) or []:
                    queue.append(_path_from_payload(linked, candidate.parent))
    frame = pd.DataFrame([asdict(item) for item in evidence])
    if frame.empty:
        latest = pd.NaT
        failures = ["no_upstream_analysis_end_date_evidence"]
    else:
        dates = pd.to_datetime(frame["evidence_date"], errors="coerce")
        latest = dates.max()
        failures = []
        if pd.isna(latest):
            failures.append("upstream_analysis_end_dates_unparseable")
        elif latest >= test:
            failures.append("upstream_analysis_overlaps_oos")
    summary = {
        "contract_version": TEMPORAL_CONTRACT_VERSION,
        "root_artifact": str(root),
        "oos_start": test.strftime("%Y-%m-%d"),
        "evidence_row_count": int(len(frame)),
        "artifact_count": int(len({str(path) for path in artifacts})),
        "latest_upstream_analysis_end": (
            pd.Timestamp(latest).strftime("%Y-%m-%d") if pd.notna(latest) else ""
        ),
        "temporal_isolation_pass": not failures,
        "failures": failures,
    }
    return frame, summary


def assert_artifact_temporal_isolation(artifact_path, *, oos_start, extra_manifest_paths=()) -> dict:
    _, summary = audit_artifact_lineage(
        artifact_path, oos_start=oos_start, extra_manifest_paths=extra_manifest_paths
    )
    if not summary["temporal_isolation_pass"]:
        raise ValueError(
            "factor artifact temporal isolation failed: "
            + "|".join(summary["failures"])
            + f"; latest={summary['latest_upstream_analysis_end']}; oos_start={summary['oos_start']}"
        )
    return summary


def write_temporal_audit(output_dir, evidence: pd.DataFrame, summary: dict) -> dict[str, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    evidence_path = target / "factor_temporal_lineage_evidence.csv"
    summary_path = target / "factor_temporal_contract.json"
    evidence.to_csv(evidence_path, index=False, encoding="utf-8-sig")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"evidence": evidence_path, "summary": summary_path}


def _manifest_candidates(path: Path) -> list[Path]:
    if path.is_file():
        candidates = [path]
        parent = path.parent
    else:
        candidates, parent = [], path
    names = (
        "factor_cabinet.json", "artifact_manifest.json", "fast_factor_judge_manifest.csv",
        "fast_factor_judge_manifest.json", "factor_temporal_contract.json",
    )
    for name in names:
        item = parent / name
        if item.exists() and item not in candidates:
            candidates.append(item)
    return candidates


def _read_payloads(path: Path) -> list[tuple[dict, str]]:
    try:
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            return [(payload, "json")] if isinstance(payload, dict) else []
        if path.suffix.lower() == ".csv":
            frame = pd.read_csv(path)
            return [(row.dropna().to_dict(), "csv") for _, row in frame.iterrows()]
    except (OSError, UnicodeError, json.JSONDecodeError, pd.errors.ParserError):
        return []
    return []


def _resolve_existing(path: Path) -> Path | None:
    if path.exists():
        return path
    # Historical manifests may contain a mojibake absolute project prefix.
    # Recover only by an unambiguous suffix inside the current workspace.
    text = str(path).replace("/", "\\")
    for anchor in ("results\\", "data\\", "functions\\"):
        pos = text.lower().find(anchor)
        if pos >= 0:
            candidate = Path(text[pos:])
            if candidate.exists():
                return candidate
    return None


def _path_from_payload(value, parent: Path) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path
    if path.exists():
        return path
    return parent / path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _optional_date(value):
    parsed = pd.to_datetime(value, errors="coerce")
    return pd.Timestamp(parsed).normalize() if pd.notna(parsed) else None


def _date(value, name: str) -> pd.Timestamp:
    parsed = _optional_date(value)
    if parsed is None:
        raise ValueError(f"{name} must be a valid date")
    return parsed
