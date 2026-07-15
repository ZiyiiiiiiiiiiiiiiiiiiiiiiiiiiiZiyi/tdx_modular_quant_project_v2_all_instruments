"""Guard against Windows path-length failures in governance result artifacts."""
from __future__ import annotations

from pathlib import Path


def main() -> int:
    from functions.decision_council.factor_source import factor_source_output_label, resolve_factor_source
    from run_governance_experiments import build_output_path

    run_id = "pruned_run20260706_183553_702097_20260710_202906"
    spec = resolve_factor_source(
        factor_source="selected_factor_cabinet",
        factor_cabinet_run_id=run_id,
    )
    label = factor_source_output_label(spec)
    assert label.startswith("cab_") and len(label) == 16, label
    root = build_output_path("governance_layer_validation", label, "hs300_csi500_a500_strict")
    artifact = root / "small_capital_branch" / "run20260711_153407" / "constraint_allocation_ledger.csv"
    candidate_gate_part = root / "small_capital_branch" / "run20260711_153407" / "_audit" / "cg" / "cg_202410.csv"
    assert len(str(artifact)) < 240, (len(str(artifact)), artifact)
    assert len(str(candidate_gate_part)) < 240, (len(str(candidate_gate_part)), candidate_gate_part)
    assert run_id not in label
    print(
        f"[PASS] cabinet output label={label}; standard artifact path={len(str(artifact))}; "
        f"candidate audit path={len(str(candidate_gate_part))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
