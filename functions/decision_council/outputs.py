"""CSV ledger outputs for exploratory decision-council runs."""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import time

import pandas as pd

from config import GOVERNANCE_OUTPUT_DIR


LEDGER_FILENAMES = {
    "ideal_portfolio_plan": "ideal_portfolio_plan.csv",
    "executable_order_plan": "executable_order_plan.csv",
    "actual_exposure_ledger": "actual_exposure_ledger.csv",
    "pending_order_ledger": "pending_order_ledger.csv",
    "safety_decision_ledger": "safety_decision_ledger.csv",
    "constraint_allocation_ledger": "constraint_allocation_ledger.csv",
    "reputation_ledger": "reputation_ledger.csv",
    "shadow_portfolio_ledger": "shadow_portfolio_ledger.csv",
    "leakage_audit_report": "leakage_audit_report.csv",
}


CSV_WRITE_RETRIES = 3
CSV_WRITE_CHUNK_ROWS = 50_000
EMPTY_ARTIFACT_COLUMNS = (
    "artifact_status",
    "schema_version",
    "status_reason",
)


def write_governance_text(text: str, path: str | Path, *, encoding: str = "utf-8") -> Path:
    """Write a text artifact with the same retry contract as ledger CSV files."""
    target = Path(path)
    last_error: OSError | None = None
    for attempt in range(1, CSV_WRITE_RETRIES + 1):
        try:
            io_target = _windows_extended_path(target)
            Path(io_target).parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(
                f"{target.name}.{os.getpid()}.{time.time_ns()}.tmp"
            )
            io_temporary = _windows_extended_path(temporary)
            Path(io_temporary).write_text(str(text), encoding=encoding)
            os.replace(io_temporary, io_target)
            return target
        except OSError as exc:
            last_error = exc
        if attempt < CSV_WRITE_RETRIES:
            time.sleep(0.5 * attempt)
    raise RuntimeError(
        f"Unable to write governance artifact after {CSV_WRITE_RETRIES} attempts: {target}"
    ) from last_error


def write_governance_csv(frame: pd.DataFrame, path: str | Path) -> Path:
    """Write a run artifact defensively against transient Windows directory races.

    A long backtest must not be discarded because an antivirus, file indexer, or
    network-backed drive makes the output directory briefly unavailable.  The
    content and CSV schema are unchanged; only directory creation, chunked
    serialization, and a short retry are added.
    """
    target = Path(path)
    if frame is None:
        frame = pd.DataFrame(columns=EMPTY_ARTIFACT_COLUMNS)
    elif len(frame.columns) == 0:
        frame = pd.DataFrame(columns=EMPTY_ARTIFACT_COLUMNS)
    last_error: OSError | None = None
    for attempt in range(1, CSV_WRITE_RETRIES + 1):
        try:
            io_target = _windows_extended_path(target)
            Path(io_target).parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(
                f"{target.name}.{os.getpid()}.{time.time_ns()}.tmp"
            )
            io_temporary = _windows_extended_path(temporary)
            frame.to_csv(
                io_temporary,
                index=False,
                encoding="utf-8-sig",
                chunksize=CSV_WRITE_CHUNK_ROWS,
            )
            os.replace(io_temporary, io_target)
            return target
        except FileNotFoundError as exc:
            last_error = exc
        except OSError as exc:
            last_error = exc
        if attempt < CSV_WRITE_RETRIES:
            time.sleep(0.5 * attempt)
    raise RuntimeError(
        f"Unable to write governance artifact after {CSV_WRITE_RETRIES} attempts: {target}"
    ) from last_error


def _windows_extended_path(path: Path) -> str:
    absolute = str(path.resolve())
    if os.name == "nt" and len(absolute) >= 248 and not absolute.startswith("\\\\?\\"):
        return "\\\\?\\" + absolute
    return absolute


@dataclass
class GovernanceLedgerBundle:
    """Collect append-only governance ledgers and save one run snapshot."""

    frames: dict[str, list[pd.DataFrame]] = field(
        default_factory=lambda: {name: [] for name in LEDGER_FILENAMES}
    )

    def append(self, ledger_name: str, frame: pd.DataFrame | dict):
        if ledger_name not in self.frames:
            raise KeyError(f"Unknown governance ledger: {ledger_name}")
        payload = pd.DataFrame([frame]) if isinstance(frame, dict) else frame.copy()
        if not payload.empty:
            self.frames[ledger_name].append(payload)

    def frame(self, ledger_name: str) -> pd.DataFrame:
        parts = self.frames[ledger_name]
        if not parts:
            return pd.DataFrame(
                columns=("ledger_status", "schema_version", "status_reason")
            )
        cleaned = [part.dropna(axis=1, how="all") for part in parts if part is not None and not part.empty]
        return (
            pd.concat(cleaned, ignore_index=True)
            if cleaned
            else pd.DataFrame(
                columns=("ledger_status", "schema_version", "status_reason")
            )
        )

    def save(self, output_dir=GOVERNANCE_OUTPUT_DIR) -> dict[str, Path]:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        saved = {}
        for ledger_name, filename in LEDGER_FILENAMES.items():
            path = output / filename
            saved[ledger_name] = write_governance_csv(self.frame(ledger_name), path)
        return saved
