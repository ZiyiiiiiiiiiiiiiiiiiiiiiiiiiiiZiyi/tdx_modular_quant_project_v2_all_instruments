"""Freeze a read-only evidence identity for an existing governance run."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


KEY_FILES = (
    "governance_daily_result.csv",
    "governance_alpha_proposals.csv",
    "governance_action_proposal_ledger.csv",
    "governance_action_plan_ledger.csv",
    "governance_execution_ledger.csv",
    "governance_trade_pairs.csv",
    "governance_research_gate_report.csv",
    "governance_unified_research_gate.csv",
    "governance_scap_admission_report.csv",
    "artifact_manifest.json",
    "run_checkpoint.json",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_snapshot(run_dir: Path) -> dict[str, object]:
    run_dir = run_dir.resolve()
    summary = pd.read_csv(run_dir / "governance_strategy_summary.csv").iloc[-1]
    daily = pd.read_csv(
        run_dir / "governance_daily_result.csv",
        usecols=["date", "nominal_nav", "actual_exposure", "holding_count"],
    )
    files = {}
    for name in KEY_FILES:
        path = run_dir / name
        files[name] = {
            "exists": path.exists(),
            "size_bytes": path.stat().st_size if path.exists() else None,
            "sha256": _sha256(path) if path.exists() else None,
        }
    return {
        "contract": "governance_run_read_only_evidence_snapshot_v1",
        "source_run": str(run_dir),
        "date_min": str(pd.to_datetime(daily["date"]).min().date()),
        "date_max": str(pd.to_datetime(daily["date"]).max().date()),
        "trading_days": int(daily["date"].nunique()),
        "terminal_nav_amount": float(pd.to_numeric(daily["nominal_nav"]).iloc[-1]),
        "total_return": float(summary.get("total_return")),
        "max_drawdown": float(summary.get("max_drawdown")),
        "average_exposure": float(pd.to_numeric(daily["actual_exposure"]).mean()),
        "closed_trade_count": int(summary.get("closed_trade_count")),
        "runtime_identity_hash": str(summary.get("runtime_identity_hash", "")),
        "code_fingerprint": str(summary.get("code_fingerprint", "")),
        "experiment_sample_role": str(summary.get("experiment_sample_role", "")),
        "files": files,
        "mutation_policy": "source_run_read_only_snapshot_written_outside_run",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    snapshot = build_snapshot(args.run_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
