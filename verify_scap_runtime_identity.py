"""Verify SCAP runtime identity is deterministic, complete, and stage-sensitive."""
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from functions.decision_council.runtime_identity import build_runtime_identity


class _FactorSpec:
    def summary_dict(self):
        return {
            "factor_source": "factor_cabinet",
            "factor_cabinet_run_id": "cab_test",
        }


def _runner(stage: str):
    return SimpleNamespace(
        capital_profile={
            "name": "small_capital_20k",
            "min_cash_buffer": 0.0,
            "objective_metric": "terminal_net_profit_after_cost",
            "special_strategy_version": "small_capital_aggressive_profit_v1",
            "scap_exit_stage": stage,
            "scap_loss_stop": -0.12,
        },
        strategy_logic_version="mainline_v3_cabinet_native",
        governance_variant="rules_based_president",
        governance_control_mode="aggressive_profit",
        initial_cash=20000.0,
        _max_positions_override=5,
        capital_usage_mode="allow_cash",
        _universe_name="hs300_csi500_a500_strict",
        _universe_mode="index_pool_strict",
        _alpha_bundle="factor_cabinet_cab_test",
        factor_source_spec=_FactorSpec(),
        pit_runtime_state="formal",
        pit_level2_runtime_state="degraded",
        factor_temporal_isolation_pass=True,
    )


dates = pd.date_range("2025-01-02", periods=3, freq="B")
first = build_runtime_identity(_runner("E0"), dates=dates, output_dir=Path("results/test"))
repeat = build_runtime_identity(_runner("E0"), dates=dates, output_dir=Path("results/test"))
stage_changed = build_runtime_identity(
    _runner("E1"), dates=dates, output_dir=Path("results/test")
)

assert first == repeat
assert first["runtime_identity_hash"] != stage_changed["runtime_identity_hash"]
assert first["code_fingerprint"]
assert first["effective_trading_days"] == 3
assert first["scap_exit_stage"] == "E0"
assert first["objective_metric"] == "terminal_net_profit_after_cost"
assert first["factor_cabinet_run_id"] == "cab_test"
print("[PASS] SCAP runtime identity contract")
