"""Verify mainline review forwards progress to both Web surfaces."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


def main() -> int:
    import build_governance_mainline_report
    import main as main_module
    import run_governance_experiments
    from functions.runtime_progress import read_progress

    original_runner = run_governance_experiments.run_single_experiment
    original_report = build_governance_mainline_report.build_report
    callbacks = []

    def fake_run_single_experiment(**kwargs):
        callback = kwargs.get("progress_callback")
        assert callback is not None
        callbacks.append(callback)
        callback({"percent": 58.0, "step": "attach_candidate_cache", "message": "cache", "detail": "unit"})
        callback({"percent": 82.0, "step": "date_complete", "message": "date", "detail": "day=1/1"})
        callback({"percent": 100.0, "step": "complete", "message": "complete", "detail": "unit"})
        return {}

    try:
        run_governance_experiments.run_single_experiment = fake_run_single_experiment
        build_governance_mainline_report.build_report = lambda **kwargs: (Path("report.md"), Path("comparison.csv"))
        main_module.run_governance_mainline_review_from_main(
            SimpleNamespace(
                governance_universes=["hs300_strict"],
                capital_profile="small_capital_branch",
                initial_cash=None,
                max_positions=None,
                min_cash_buffer=None,
                capital_usage_mode=None,
                governance_alpha_bundle="diversified_pre_screen_bundle_v2",
                factor_source="latest_factor_cabinet",
                factor_cabinet_run_id="",
                factor_cabinet_path="",
                governance_start_date="2021-01-04",
                governance_end_date="2021-01-04",
                governance_max_days=1,
                governance_shadow_portfolios=False,
                no_live_monitor=True,
                governance_control_mode="normal",
                disable_alpha_collapse_exit=False,
            )
        )
    finally:
        run_governance_experiments.run_single_experiment = original_runner
        build_governance_mainline_report.build_report = original_report

    progress = read_progress()
    assert callbacks
    assert progress["task_name"] == "governance_mainline_review", progress
    assert progress["status"] == "complete", progress
    assert progress["percent"] == 100.0, progress
    print("[PASS] governance mainline review forwards stage/date progress to Web")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
