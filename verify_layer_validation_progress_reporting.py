from types import SimpleNamespace

import pandas as pd


def _args() -> SimpleNamespace:
    return SimpleNamespace(
        governance_universes=["hs300_strict"],
        capital_profile="small_capital_branch",
        initial_cash=None,
        max_positions=None,
        min_cash_buffer=None,
        capital_usage_mode=None,
        governance_start_date="2021-01-04",
        governance_end_date="2021-01-04",
        governance_max_days=1,
        no_live_monitor=True,
        governance_control_mode="normal",
        disable_alpha_collapse_exit=False,
        factor_source="latest_factor_cabinet",
        factor_cabinet_run_id="",
        factor_cabinet_path="",
    )


def main() -> int:
    check_layer_validation_runtime_progress()
    check_run_single_experiment_progress_hooks()
    check_layer_validation_live_monitor_stage_progress()
    check_web_defaults_selected_factor_cabinet()
    return 0


def check_layer_validation_runtime_progress() -> None:
    import main as main_module
    import run_governance_experiments
    from functions.runtime_progress import read_progress

    captured = []
    original = run_governance_experiments.run_single_experiment

    def fake_run_single_experiment(**kwargs):
        callback = kwargs.get("progress_callback")
        assert callback is not None, "layer validation did not pass progress_callback"
        for payload in (
            {"percent": 4.0, "step": "resolve_factor_source", "message": "resolving", "detail": "unit"},
            {"percent": 80.0, "step": "run_backtest", "message": "running", "detail": "unit"},
            {"percent": 100.0, "step": "complete", "message": "complete", "detail": "unit"},
        ):
            captured.append(payload)
            callback(payload)
        return {}

    try:
        run_governance_experiments.run_single_experiment = fake_run_single_experiment
        main_module.run_governance_layer_validation_from_main(_args())
    finally:
        run_governance_experiments.run_single_experiment = original

    assert [payload["step"] for payload in captured] == [
        "resolve_factor_source",
        "run_backtest",
        "complete",
    ]
    progress = read_progress()
    assert progress["task_name"] == "governance_layer_validation", progress
    assert progress["status"] == "complete", progress
    assert progress["step"] == "complete", progress
    assert progress["percent"] == 100.0, progress
    print("[PASS] layer validation reports detailed runtime progress")


def check_run_single_experiment_progress_hooks() -> None:
    import run_governance_experiments as exp

    captured = []
    original_loader = exp._load_governance_features
    original_runner = exp.GovernanceBacktestRunner

    def callback(payload):
        captured.append(dict(payload))

    def fake_loader(
        start_date,
        end_date,
        *,
        alpha_models,
        allowed_instrument_types,
        factor_spec=None,
        progress_callback=None,
    ):
        _ = factor_spec
        progress_callback(
            {
                "percent": 32.0,
                "step": "read_feature_parquet",
                "message": "reading governance feature parquet",
                "detail": "unit",
            }
        )
        return pd.DataFrame(
            [
                {
                    "date": "2021-01-04",
                    "symbol": "sh510300",
                    "instrument_type": "etf_fund",
                    "open": 10.0,
                    "close": 10.0,
                    "amount": 1.0,
                    "volatility_20": 0.0,
                }
            ]
        )

    class FakeRunner:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        def run(self, **kwargs):
            progress_callback = kwargs.get("progress_callback")
            progress_callback(
                {
                    "percent": 93.0,
                    "step": "date_complete",
                    "message": "completed governance date 2021-01-04",
                    "detail": "day=1/1",
                }
            )
            return {}

    try:
        exp._load_governance_features = fake_loader
        exp.GovernanceBacktestRunner = FakeRunner
        exp.run_single_experiment(
            variant_name="governance_layer_validation",
            alpha_bundle="diversified_pre_screen_bundle_v2",
            universe_name="hs300_strict",
            start_date="2021-01-04",
            end_date="2021-01-04",
            max_days=1,
            show_live_monitor=False,
            enable_shadow_portfolios=False,
            factor_source="latest_factor_cabinet",
            progress_callback=callback,
        )
    finally:
        exp._load_governance_features = original_loader
        exp.GovernanceBacktestRunner = original_runner

    steps = [payload.get("step") for payload in captured]
    assert "resolve_factor_source" in steps, steps
    assert "read_feature_parquet" in steps, steps
    assert "run_backtest" in steps, steps
    assert "date_complete" in steps, steps
    assert "complete" in steps, steps
    print("[PASS] run_single_experiment emits stage and date-loop progress")


def check_layer_validation_live_monitor_stage_progress() -> None:
    import main as main_module
    import run_governance_experiments
    import functions.decision_council.live_monitor as live_monitor_module

    stage_rows = []
    sessions = []
    original_runner = run_governance_experiments.run_single_experiment
    original_monitor = live_monitor_module.GovernanceLiveMonitor

    class FakeMonitor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def start_session(self, **kwargs):
            sessions.append(kwargs)

        def report_stage(self, **kwargs):
            stage_rows.append(kwargs)

    def fake_run_single_experiment(**kwargs):
        callback = kwargs["progress_callback"]
        callback(
            {
                "percent": 80.0,
                "step": "run_backtest",
                "message": "running date loop",
                "detail": "unit",
            }
        )
        callback(
            {
                "percent": 81.0,
                "step": "process_date",
                "message": "processing governance date 2021-01-04",
                "detail": "day=1/1",
            }
        )
        callback(
            {
                "percent": 82.0,
                "step": "date_complete",
                "message": "completed governance date 2021-01-04",
                "detail": "day=1/1",
            }
        )
        callback(
            {
                "percent": 58.0,
                "step": "attach_candidate_cache",
                "message": "attaching generated candidate factor cache",
                "detail": "unit",
            }
        )
        callback(
            {
                "percent": 100.0,
                "step": "complete",
                "message": "complete",
                "detail": "unit",
            }
        )
        return {}

    args = _args()
    args.no_live_monitor = False
    try:
        run_governance_experiments.run_single_experiment = fake_run_single_experiment
        live_monitor_module.GovernanceLiveMonitor = FakeMonitor
        main_module.run_governance_layer_validation_from_main(args)
    finally:
        run_governance_experiments.run_single_experiment = original_runner
        live_monitor_module.GovernanceLiveMonitor = original_monitor

    assert sessions, "live monitor session was not started before data preparation"
    assert stage_rows, "live monitor did not receive stage progress"
    assert any(row["step"] == "attach_candidate_cache" for row in stage_rows), stage_rows
    assert not any(row["step"] in {"run_backtest", "process_date", "date_complete"} for row in stage_rows), stage_rows
    assert stage_rows[-1]["step"] == "complete", stage_rows
    print("[PASS] layer validation sends pre-trade stage progress without overwriting date updates")


def check_web_defaults_selected_factor_cabinet() -> None:
    import main_launcher_web

    html = main_launcher_web._render_run_html()
    assert 'factorSource.value = "selected_factor_cabinet"' in html
    assert 'factorSourceNode.value : "selected_factor_cabinet"' in html
    print("[PASS] web launcher defaults factor source to selected_factor_cabinet")


if __name__ == "__main__":
    raise SystemExit(main())
