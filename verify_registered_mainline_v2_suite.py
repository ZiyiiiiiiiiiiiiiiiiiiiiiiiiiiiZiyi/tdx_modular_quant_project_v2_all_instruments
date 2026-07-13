"""Verify the four mainline comparisons are fixed and non-duplicated."""
from __future__ import annotations

from pathlib import Path

import run_governance_experiments as module


def main() -> int:
    calls = []
    original = module.run_single_experiment

    def fake_run_single_experiment(**kwargs):
        calls.append(kwargs)
        return {"governance_strategy_summary": Path(f"{kwargs['output_dir_suffix']}.csv")}

    module.run_single_experiment = fake_run_single_experiment
    try:
        result = module.run_registered_mainline_v2_suite(
            universe_name="hs300_strict",
            start_date="2024-01-01",
            end_date="2024-01-31",
            max_days=5,
            factor_source="latest_factor_cabinet",
        )
    finally:
        module.run_single_experiment = original
    assert list(result) == [
        "production_v1", "mainline_v2", "mainline_v2_without_regime", "mainline_v2_simple_exit"
    ]
    signatures = {
        (call["strategy_logic_version"], call["regime_overlay_mode_override"], call["exit_mode_override"])
        for call in calls
    }
    assert len(calls) == len(signatures) == 4
    assert all(call["factor_source"] == "latest_factor_cabinet" for call in calls)
    without_regime = next(call for call in calls if call["output_dir_suffix"] == "registered_mainline_v2_without_regime")
    simple_exit = next(call for call in calls if call["output_dir_suffix"] == "registered_mainline_v2_simple_exit")
    assert without_regime["regime_overlay_mode_override"] == "off"
    assert without_regime["enable_market_regime_policy_override"] is False
    assert simple_exit["exit_mode_override"] == "simple"
    print("[PASS] four pre-registered mainline experiments are distinct and cabinet-routed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
