"""Build a fail-closed Phase 8 gate verdict from persisted evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def _truth(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "pass", "passed"}


def build_verdict(run_dir: Path, derived_root: Path) -> dict[str, object]:
    research_path = run_dir / "governance_research_gate_report.csv"
    unified_path = run_dir / "governance_unified_research_gate.csv"
    admission_path = run_dir / "governance_scap_admission_report.csv"
    research = pd.read_csv(research_path)
    unified = pd.read_csv(unified_path)
    admission = pd.read_csv(admission_path)

    failed_research = research.loc[
        ~research["pass_flag"].map(_truth), "gate_name"
    ].astype(str).tolist()
    failed_unified = unified.loc[
        ~unified["gate_pass"].map(_truth), "check"
    ].astype(str).tolist()
    admission_row = admission.iloc[-1]
    production_pass = _truth(admission_row.get("production_eligible", False))

    required_products = {
        "phase1_workbook": derived_root / "phase1_coverage_semantics_20260805",
        "phase3_regime_diagnostics": derived_root / "phase3_regime_factor_diagnostics_20260805",
        "phase5_buy_quality": derived_root / "phase5_buy_quality_diagnostics_20260805",
        "phase7_full_universe_oos": derived_root / "phase7_full_universe_oos_20260805",
    }
    missing_products = [
        name for name, path in required_products.items() if not path.exists()
    ]
    engineering_pass = not missing_products
    research_pass = not failed_research and not failed_unified

    return {
        "contract": "phase8_fail_closed_gate_verdict_v1",
        "source_run": str(run_dir.resolve()),
        "engineering_gate": "pass" if engineering_pass else "blocked",
        "engineering_missing_products": missing_products,
        "research_gate": "pass" if research_pass else "blocked",
        "failed_research_checks": failed_research,
        "failed_unified_checks": failed_unified,
        "production_gate": "pass" if production_pass else "blocked",
        "production_block_reason": str(
            admission_row.get("production_block_reason", "missing")
        ),
        "research_stage_eligible": _truth(
            admission_row.get("research_stage_eligible", False)
        ),
        "prospective_paper_gate_pass": _truth(
            admission_row.get("prospective_paper_gate_pass", False)
        ),
        "production_eligible": production_pass,
        "decision": (
            "engineering_products_accepted_no_trading_authority"
            if engineering_pass and not production_pass
            else "blocked_missing_engineering_evidence"
            if not engineering_pass
            else "production_eligible"
        ),
        "source_files": [
            str(research_path.resolve()),
            str(unified_path.resolve()),
            str(admission_path.resolve()),
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("derived_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = build_verdict(args.run_dir, args.derived_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
