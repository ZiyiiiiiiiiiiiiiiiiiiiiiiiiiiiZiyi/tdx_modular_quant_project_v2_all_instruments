"""Verify E0-E4 differ only by their registered exit permissions."""
from functions.decision_council.small_capital_aggressive import (
    build_scap_exit_stage_contract,
)


matrix = build_scap_exit_stage_contract("E3")
assert matrix["exit_stage"].tolist() == ["E0", "E1", "E2", "E3", "E4"]
assert matrix["is_current_stage"].sum() == 1
assert matrix.loc[matrix["exit_stage"].eq("E3"), "is_current_stage"].iloc[0]
assert not matrix.loc[matrix["exit_stage"].eq("E0"), "signal_failure_exit_enabled"].iloc[0]
assert matrix.loc[matrix["exit_stage"].eq("E1"), "signal_failure_exit_enabled"].iloc[0]
assert matrix.loc[matrix["exit_stage"].eq("E3"), "loss_containment_exit_enabled"].iloc[0]
assert not matrix.loc[matrix["exit_stage"].eq("E3"), "profit_giveback_exit_enabled"].iloc[0]
assert matrix.loc[matrix["exit_stage"].eq("E4"), "profit_giveback_exit_enabled"].iloc[0]
assert not matrix["active_replacement_enabled"].any()
assert matrix["experiment_contract"].nunique() == 1
print("[PASS] SCAP E0-E4 single-variable experiment contract")
