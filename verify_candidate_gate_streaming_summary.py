from __future__ import annotations

from pathlib import Path

import pandas as pd

from functions.decision_council.candidate_funnel_audit import (
    build_control_trigger_summary_from_csv_parts,
    build_entry_gate_summary_from_csv_parts,
)


def main() -> None:
    root = Path("reports/verify_candidate_gate_streaming_summary")
    root.mkdir(parents=True, exist_ok=True)
    paths = []
    for month, values in (("01", [True, False, True]), ("02", [False, False])):
        path = root / f"candidate_gates_2024{month}.csv"
        pd.DataFrame({
            "entry_pass": values,
            "risk_pass": [True] * len(values),
            "first_block_reason": ["entry"] * len(values),
            "strategy_logic_version": ["production_v1"] * len(values),
            "probability_gate_evaluated": [True] * len(values),
            "probability_gate_changed_decision": values,
            "paper_loss_containment_exit": values,
            "loss_containment_exit": [False] * len(values),
            "paper_thesis_failure_exit": values,
            "thesis_failure_exit": values,
        }).to_csv(path, index=False)
        paths.append(path)
    summary = build_entry_gate_summary_from_csv_parts(paths, chunksize=2).set_index("gate")
    assert int(summary.loc["entry_pass", "candidate_count"]) == 5
    assert int(summary.loc["entry_pass", "pass_count"]) == 2
    assert int(summary.loc["risk_pass", "pass_count"]) == 5
    triggers = build_control_trigger_summary_from_csv_parts(
        paths,
        order_plan=pd.DataFrame(),
        execution_ledger=pd.DataFrame(),
        chunksize=2,
    ).set_index("control")
    assert int(triggers.loc["probability_gate", "evaluated_count"]) == 5
    assert int(triggers.loc["probability_gate", "active_trigger_count"]) == 2
    assert triggers.loc["probability_gate", "audit_scope"] == "full_streamed_history"
    assert int(triggers.loc["loss_containment_exit", "paper_trigger_count"]) == 2
    assert int(triggers.loc["loss_containment_exit", "active_trigger_count"]) == 0
    assert int(triggers.loc["thesis_failure_exit", "paper_trigger_count"]) == 2
    assert int(triggers.loc["thesis_failure_exit", "active_trigger_count"]) == 2
    print("[PASS] candidate gate summary streams monthly parts without full concat")


if __name__ == "__main__":
    main()
