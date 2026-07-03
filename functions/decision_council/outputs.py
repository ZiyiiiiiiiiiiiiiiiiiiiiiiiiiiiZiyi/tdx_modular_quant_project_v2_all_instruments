"""CSV ledger outputs for exploratory decision-council runs."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

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
            return pd.DataFrame()
        cleaned = [part.dropna(axis=1, how="all") for part in parts if part is not None and not part.empty]
        return pd.concat(cleaned, ignore_index=True) if cleaned else pd.DataFrame()

    def save(self, output_dir=GOVERNANCE_OUTPUT_DIR) -> dict[str, Path]:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        saved = {}
        for ledger_name, filename in LEDGER_FILENAMES.items():
            path = output / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            self.frame(ledger_name).to_csv(path, index=False, encoding="utf-8-sig")
            saved[ledger_name] = path
        return saved
