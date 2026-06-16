# -*- coding: utf-8 -*-
"""Resume external data and rebuild every derived artifact after VPN is disabled.

This is the user-facing one-click completion entry point. It is intentionally
restartable: successful stages and strategy batches are recorded in a JSON
state file, while provider fetchers keep their own staged resume files.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
import hashlib
import json
import msvcrt
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from config import (
    ADJUSTMENT_FACTORS_PARQUET,
    AUTO_COMPLETE_EXTERNAL_DATA_PYTHON,
    AUTO_COMPLETE_LOCK_PATH,
    AUTO_COMPLETE_LOCAL_GOVERNANCE_END_DATE,
    AUTO_COMPLETE_LOCAL_GOVERNANCE_START_DATE,
    AUTO_COMPLETE_MAIN_PYTHON,
    AUTO_COMPLETE_MAX_STRATEGY_WORKERS,
    AUTO_COMPLETE_STATE_PATH,
    CORPORATE_ACTIONS_PARQUET,
    MARKET_CAP_PARQUET,
    REPORT_DIR,
    STRATEGY_BATCH_SIZE_DEFAULT,
    STRATEGY_END_DATE,
    STRATEGY_START_DATE,
    AUTO_COMPLETE_FETCH_BATCH_DELAY_SECONDS,
    AUTO_COMPLETE_FETCH_BATCH_SIZE,
    AUTO_COMPLETE_FETCH_DIVIDEND_BATCH_SIZE,
    AUTO_COMPLETE_FETCH_LOGIN_RETRIES,
    AUTO_COMPLETE_FETCH_LOGIN_RETRY_DELAY_SECONDS,
    AUTO_COMPLETE_FETCH_REQUEST_DELAY_SECONDS,
    AUTO_COMPLETE_FETCH_SOCKET_TIMEOUT_SECONDS,
    AUTO_COMPLETE_MARKET_CAP_SOURCE,
    CLI_AUTO_COMPLETE_START_BATCH_INDEX,
    CLI_AUTO_COMPLETE_STRATEGY_WORKERS,
    CLI_GOVERNANCE_MAX_DAYS,
    CLI_GOVERNANCE_SAFETY_PROXY_MODE,
    assert_valid_configuration,
)
from functions.date_window import window_identity
from functions.strategy_registry import list_strategy_names
from functions.pipeline_cache import build_signature, code_file_fingerprint


PROJECT_DIR = Path(__file__).resolve().parent
MAIN_PYTHON = AUTO_COMPLETE_MAIN_PYTHON
EXTERNAL_DATA_PYTHON = AUTO_COMPLETE_EXTERNAL_DATA_PYTHON
STATE_PATH = AUTO_COMPLETE_STATE_PATH
LOCK_PATH = AUTO_COMPLETE_LOCK_PATH
DEFAULT_LOCAL_GOVERNANCE_START_DATE = AUTO_COMPLETE_LOCAL_GOVERNANCE_START_DATE
DEFAULT_LOCAL_GOVERNANCE_END_DATE = AUTO_COMPLETE_LOCAL_GOVERNANCE_END_DATE
MAX_STRATEGY_WORKERS = AUTO_COMPLETE_MAX_STRATEGY_WORKERS


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print the workflow without running commands.")
    parser.add_argument("--reset-state", action="store_true", help="Discard recorded stage progress and rerun all stages.")
    parser.add_argument(
        "--full-run",
        action="store_true",
        help="Run full governance history. Default is a local 2021 calendar-year run.",
    )
    parser.add_argument("--force-data-refresh", action="store_true", help="Re-fetch and rebuild data even when spot checks pass.")
    parser.add_argument("--skip-external-fetch", action="store_true", help="Use already published provider artifacts.")
    parser.add_argument("--skip-market-cap", action="store_true", help="Keep the published market-cap artifact unchanged.")
    parser.add_argument(
        "--market-cap-existing-reports-only",
        action="store_true",
        help="Use downloaded TDX finance ZIP files without fetching the latest report list.",
    )
    parser.add_argument("--skip-feature-rebuild", action="store_true", help="Keep the current feature parquet unchanged.")
    parser.add_argument("--skip-strategy-rerun", action="store_true", help="Do not regenerate and backtest all strategies.")
    parser.add_argument("--skip-governance", action="store_true", help="Do not run decision-council stages.")
    parser.add_argument("--skip-governance-industrial-build", action="store_true", help="Reuse existing industrial governance artifacts.")
    parser.add_argument("--skip-governance-backtest", action="store_true", help="Skip the daily decision-council backtest only.")
    parser.add_argument("--governance-start-date", default=None, help="Optional first governance backtest date.")
    parser.add_argument("--governance-end-date", default=None, help="Optional last governance backtest date.")
    parser.add_argument("--governance-max-days", type=int, default=CLI_GOVERNANCE_MAX_DAYS, help="Optional governance smoke-run limit.")
    parser.add_argument(
        "--safety-proxy-mode",
        choices=["strict", "degraded_backtest"],
        default=CLI_GOVERNANCE_SAFETY_PROXY_MODE,
        help="Use strict mode for normal one-click runs; degraded mode is exploratory only.",
    )
    parser.add_argument("--batch-size", type=int, default=STRATEGY_BATCH_SIZE_DEFAULT, help="Strategies per fresh subprocess. Use 1 on low-memory machines.")
    parser.add_argument("--start-batch-index", type=int, default=CLI_AUTO_COMPLETE_START_BATCH_INDEX, help="Start strategy rerun from this zero-based batch.")
    parser.add_argument(
        "--strategy-workers",
        type=int,
        default=CLI_AUTO_COMPLETE_STRATEGY_WORKERS,
        help="Parallel strategy batch subprocesses. Use 1 for lowest memory; 2 is the hard cap.",
    )
    args = parser.parse_args()
    return _apply_local_runtime_defaults(args)


def _apply_local_runtime_defaults(args):
    args.strategy_workers = max(1, min(int(args.strategy_workers), MAX_STRATEGY_WORKERS))
    args.local_fast_mode = not args.full_run
    args.governance_date_range_defaulted = False
    if args.local_fast_mode:
        if args.governance_start_date is None and args.governance_end_date is None and args.governance_max_days is None:
            args.governance_start_date = DEFAULT_LOCAL_GOVERNANCE_START_DATE
            args.governance_end_date = DEFAULT_LOCAL_GOVERNANCE_END_DATE
            args.governance_date_range_defaulted = True
    return args


def main():
    with _single_instance_lock():
        _run_workflow()


def _run_workflow():
    assert_valid_configuration()
    args = parse_args()
    _validate_interpreters()
    state = {} if args.reset_state else _load_state()
    _print_header(args, state)

    tdx_daily_rebuilt = False
    if args.force_data_refresh or not _validate_existing_artifact(
        state,
        "tdx_daily_artifact_spot_check",
        [MAIN_PYTHON, "validate_existing_data_artifacts.py", "--dataset", "tdx-daily"],
        dry_run=args.dry_run,
    ):
        _run_stage(
            state,
            "tdx_daily_rebuild",
            [MAIN_PYTHON, "rebuild_tdx_daily_data.py"],
            dry_run=args.dry_run,
            force_run=True,
        )
        tdx_daily_rebuilt = True
    else:
        print("\n[REUSE] tdx_daily_rebuild: existing raw and clean artifacts passed distributed spot check")

    external_data_rebuilt = False
    if args.skip_external_fetch:
        _require_artifacts([ADJUSTMENT_FACTORS_PARQUET, CORPORATE_ACTIONS_PARQUET])
        _validate_existing_artifact(
            state,
            "baostock_artifact_spot_check",
            [MAIN_PYTHON, "validate_existing_data_artifacts.py", "--dataset", "baostock"],
            dry_run=args.dry_run,
            raise_on_failure=True,
        )
    elif args.force_data_refresh or tdx_daily_rebuilt or not _validate_existing_artifact(
        state,
        "baostock_artifact_spot_check",
        [MAIN_PYTHON, "validate_existing_data_artifacts.py", "--dataset", "baostock"],
        dry_run=args.dry_run,
    ):
        _run_stage(
            state,
            "network_diagnosis",
            [EXTERNAL_DATA_PYTHON, "diagnose_external_data_environment.py", "--require-network"],
            dry_run=args.dry_run,
            always_run=True,
        )
        _run_stage(
            state,
            "baostock_reference_data",
            [
                EXTERNAL_DATA_PYTHON,
                "fetch_baostock_reference_data.py",
                "--publish",
                "--resume",
                "--batch-size",
                str(AUTO_COMPLETE_FETCH_BATCH_SIZE),
                "--dividend-batch-size",
                str(AUTO_COMPLETE_FETCH_DIVIDEND_BATCH_SIZE),
                "--request-delay-seconds",
                str(AUTO_COMPLETE_FETCH_REQUEST_DELAY_SECONDS),
                "--batch-delay-seconds",
                str(AUTO_COMPLETE_FETCH_BATCH_DELAY_SECONDS),
                "--login-retries",
                str(AUTO_COMPLETE_FETCH_LOGIN_RETRIES),
                "--login-retry-delay-seconds",
                str(AUTO_COMPLETE_FETCH_LOGIN_RETRY_DELAY_SECONDS),
                "--socket-timeout-seconds",
                str(AUTO_COMPLETE_FETCH_SOCKET_TIMEOUT_SECONDS),
            ],
            dry_run=args.dry_run,
            force_run=True,
        )
        external_data_rebuilt = True
    else:
        print("\n[REUSE] baostock_reference_data: existing artifacts passed deterministic spot check")

    market_cap_rebuilt = False
    if args.skip_market_cap:
        _require_artifacts([MARKET_CAP_PARQUET])
        _validate_existing_artifact(
            state,
            "market_cap_artifact_spot_check",
            [MAIN_PYTHON, "validate_existing_data_artifacts.py", "--dataset", "market-cap"],
            dry_run=args.dry_run,
            raise_on_failure=True,
        )
    elif args.force_data_refresh or not _validate_existing_artifact(
        state,
        "market_cap_artifact_spot_check",
        [MAIN_PYTHON, "validate_existing_data_artifacts.py", "--dataset", "market-cap"],
        dry_run=args.dry_run,
    ):
        command = [
            EXTERNAL_DATA_PYTHON,
            "fetch_market_cap_history.py",
            "--source",
            AUTO_COMPLETE_MARKET_CAP_SOURCE,
            "--publish",
        ]
        if args.market_cap_existing_reports_only:
            command.append("--use-existing-reports-only")
        _run_stage(state, "market_cap_history", command, dry_run=args.dry_run, force_run=True)
        market_cap_rebuilt = True
    else:
        print("\n[REUSE] market_cap_history: existing artifact passed distributed spot check")

    upstream_data_rebuilt = tdx_daily_rebuilt or external_data_rebuilt or market_cap_rebuilt
    if args.skip_feature_rebuild:
        _validate_existing_artifact(
            state,
            "feature_artifact_spot_check",
            [MAIN_PYTHON, "validate_existing_data_artifacts.py", "--dataset", "features"],
            dry_run=args.dry_run,
            raise_on_failure=True,
        )
        _record_reused_stage(
            state,
            "feature_rebuild",
            [MAIN_PYTHON, "rebuild_feature_data.py"],
            dry_run=args.dry_run,
            extra={"skip_feature_rebuild": True},
        )
    elif args.force_data_refresh or upstream_data_rebuilt or not _validate_existing_artifact(
        state,
        "feature_artifact_spot_check",
        [MAIN_PYTHON, "validate_existing_data_artifacts.py", "--dataset", "features"],
        dry_run=args.dry_run,
    ):
        _run_stage(
            state,
            "feature_rebuild",
            [MAIN_PYTHON, "rebuild_feature_data.py"],
            dry_run=args.dry_run,
            force_run=True,
        )
    else:
        print("\n[REUSE] feature_rebuild: existing artifact passed distributed spot check")
        _record_reused_stage(
            state,
            "feature_rebuild",
            [MAIN_PYTHON, "rebuild_feature_data.py"],
            dry_run=args.dry_run,
            extra={"reused_after_spot_check": True},
        )

    if not args.skip_strategy_rerun:
        _run_strategy_batches(state, args, dry_run=args.dry_run)
        _run_stage(
            state,
            "strategy_summary_finalize",
            [MAIN_PYTHON, "finalize_strategy_batch_summary.py"],
            dry_run=args.dry_run,
            always_run=True,
        )

    if not args.skip_governance:
        if not args.skip_governance_industrial_build:
            _run_stage(
                state,
                "decision_council_industrial_build",
                [MAIN_PYTHON, "run_governance_industrial_pipeline.py"],
                dry_run=args.dry_run,
                extra={"governance_code_signature": _governance_code_signature()},
            )
        else:
            print("\n[SKIP] decision_council_industrial_build: requested by --skip-governance-industrial-build")
        governance_command = [
            MAIN_PYTHON,
            "run_governance_backtest.py",
            "--safety-proxy-mode",
            args.safety_proxy_mode,
        ]
        if args.governance_start_date:
            governance_command.extend(["--start-date", args.governance_start_date])
        if args.governance_end_date:
            governance_command.extend(["--end-date", args.governance_end_date])
        if args.governance_max_days is not None:
            governance_command.extend(["--max-days", str(args.governance_max_days)])
        if not args.skip_governance_backtest:
            _run_stage(
                state,
                "decision_council_backtest",
                governance_command,
                dry_run=args.dry_run,
                extra={"governance_code_signature": _governance_code_signature()},
            )
        else:
            print("\n[SKIP] decision_council_backtest: requested by --skip-governance-backtest")
        _run_stage(
            state,
            "decision_council_verification",
            [MAIN_PYTHON, "verify_decision_council_phase_one.py"],
            dry_run=args.dry_run,
            always_run=True,
        )
        _run_stage(
            state,
            "decision_council_stress_verification",
            [MAIN_PYTHON, "verify_decision_council_stress.py"],
            dry_run=args.dry_run,
            always_run=True,
        )
        _run_stage(
            state,
            "decision_council_p0_p1_5_verification",
            [MAIN_PYTHON, "verify_governance_p0_p1_5.py"],
            dry_run=args.dry_run,
            always_run=True,
        )
        _run_stage(
            state,
            "decision_council_industrial_verification",
            [MAIN_PYTHON, "verify_governance_industrial_pipeline.py"],
            dry_run=args.dry_run,
            always_run=True,
        )
        _run_stage(
            state,
            "decision_council_evaluation",
            [MAIN_PYTHON, "evaluate_governance_results.py"],
            dry_run=args.dry_run,
            always_run=True,
        )

    _run_stage(
        state,
        "formal_artifacts",
        [MAIN_PYTHON, "build_formal_artifacts.py"],
        dry_run=args.dry_run,
        always_run=True,
    )
    _run_stage(
        state,
        "research_readiness_reports",
        [MAIN_PYTHON, "generate_research_readiness_reports.py"],
        dry_run=args.dry_run,
        always_run=True,
    )
    _run_stage(
        state,
        "v6_governance_artifacts",
        [MAIN_PYTHON, "build_v6_artifacts.py"],
        dry_run=args.dry_run,
        always_run=True,
    )
    for stage_name, script_name in [
        ("centralized_configuration_verification", "verify_centralized_configuration.py"),
        ("date_window_verification", "verify_date_window_enforcement.py"),
        ("v6_core_verification", "verify_v6_core.py"),
        ("v6_governance_verification", "verify_v6_governance.py"),
        ("v6_decision_pipeline_verification", "verify_v6_decision_pipeline.py"),
        ("probability_calibration_verification", "verify_probability_calibration.py"),
        ("v6_completion_audit", "audit_v6_completion.py"),
    ]:
        _run_stage(
            state,
            stage_name,
            [MAIN_PYTHON, script_name],
            dry_run=args.dry_run,
            always_run=True,
        )
    _run_stage(
        state,
        "roadmap_audit",
        [MAIN_PYTHON, "audit_roadmap_completion.py"],
        dry_run=args.dry_run,
        always_run=True,
    )
    _run_stage(
        state,
        "mainline_output_verification",
        [MAIN_PYTHON, "verify_mainline_outputs.py"],
        dry_run=args.dry_run,
        always_run=True,
    )

    if args.dry_run:
        print("\nDry run completed. No command was executed.")
    else:
        state["workflow_completed_at"] = _now()
        _save_state(state)
        print("\nAll automatic completion stages finished.")
        print("State file:", STATE_PATH)
        print("Review formal admission report:", REPORT_DIR / "formal_admission_report.csv")


def _run_strategy_batches(state, args, dry_run):
    names = list_strategy_names()
    batch_size = max(int(args.batch_size), 1)
    batch_count = (len(names) + batch_size - 1) // batch_size
    batch_specs = []
    strategy_window = window_identity(STRATEGY_START_DATE, STRATEGY_END_DATE)
    for batch_index in range(max(args.start_batch_index, 0), batch_count):
        batch_names = names[batch_index * batch_size:(batch_index + 1) * batch_size]
        stage_name = f"strategy_batch_{batch_index:03d}"
        command = [
            MAIN_PYTHON,
            "run_strategy_batches.py",
            "--mode",
            "all",
            "--batch-size",
            str(batch_size),
            "--batch-index",
            str(batch_index),
        ]
        batch_specs.append(
            (
                stage_name,
                command,
                {
                    "strategy_names": batch_names,
                    "strategy_code_signature": _strategy_code_signature(),
                    "strategy_date_window": strategy_window,
                },
            )
        )
    if args.strategy_workers <= 1 or dry_run:
        for stage_name, command, extra in batch_specs:
            _run_stage(state, stage_name, command, dry_run=dry_run, extra=extra)
        return
    _run_strategy_batches_parallel(state, batch_specs, args.strategy_workers)


def _run_strategy_batches_parallel(state, batch_specs, workers):
    runnable = []
    for stage_name, command, extra in batch_specs:
        command = [str(item) for item in command]
        record = state.get("stages", {}).get(stage_name, {})
        if (
            record.get("status") == "completed"
            and record.get("command") == command
            and record.get("extra", {}) == extra
        ):
            print(f"\n[SKIP] {stage_name}: already completed")
            continue
        print(f"\n[QUEUE] {stage_name}")
        print(_format_command(command))
        _record_stage(state, stage_name, "queued", command, extra=extra)
        runnable.append((stage_name, command, extra))
    if not runnable:
        return
    print(f"\n[PARALLEL] Running strategy batches with workers={workers}.")
    failures = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {}
        for stage_name, command, extra in runnable:
            _record_stage(state, stage_name, "running", command, extra=extra)
            future_map[executor.submit(_run_subprocess, command)] = (stage_name, command, extra)
        for future in as_completed(future_map):
            stage_name, command, extra = future_map[future]
            try:
                future.result()
            except subprocess.CalledProcessError as exc:
                _record_stage(state, stage_name, "failed", command, extra={"returncode": exc.returncode, **extra})
                failures.append(stage_name)
            else:
                _record_stage(state, stage_name, "completed", command, extra=extra)
                print(f"[DONE] {stage_name}")
    if failures:
        raise RuntimeError("Strategy batch failures: " + ", ".join(failures))


def _run_stage(state, stage_name, command, *, dry_run, always_run=False, force_run=False, extra=None):
    command = [str(item) for item in command]
    record = state.get("stages", {}).get(stage_name, {})
    if (
        not always_run
        and not force_run
        and record.get("status") == "completed"
        and record.get("command") == command
        and record.get("extra", {}) == (extra or {})
    ):
        print(f"\n[SKIP] {stage_name}: already completed")
        return
    print(f"\n[RUN] {stage_name}")
    print(_format_command(command))
    if dry_run:
        return
    _record_stage(state, stage_name, "running", command, extra=extra)
    try:
        _run_subprocess(command)
    except subprocess.CalledProcessError as exc:
        _record_stage(state, stage_name, "failed", command, extra={"returncode": exc.returncode, **(extra or {})})
        if stage_name == "network_diagnosis":
            raise RuntimeError(
                "External-data network diagnosis failed. Disable VPN/proxy software, "
                "check firewall access to public-api.baostock.com:10030, then rerun this script."
            ) from exc
        raise
    _record_stage(state, stage_name, "completed", command, extra=extra)
    if stage_name == "feature_rebuild":
        _invalidate_strategy_results(state)


def _run_subprocess(command):
    child_env = os.environ.copy()
    child_env["PYTHONUNBUFFERED"] = "1"
    return subprocess.run(command, cwd=PROJECT_DIR, check=True, env=child_env)


def _validate_existing_artifact(state, stage_name, command, *, dry_run, raise_on_failure=False):
    command = [str(item) for item in command]
    print(f"\n[SPOT CHECK] {stage_name}")
    print(_format_command(command))
    if dry_run:
        print("[DRY RUN] Existing artifact will be reused only if this spot check passes.")
        return True
    _record_stage(state, stage_name, "running", command)
    try:
        child_env = os.environ.copy()
        child_env["PYTHONUNBUFFERED"] = "1"
        subprocess.run(command, cwd=PROJECT_DIR, check=True, env=child_env)
    except subprocess.CalledProcessError as exc:
        _record_stage(state, stage_name, "failed", command, extra={"returncode": exc.returncode})
        print(f"[REBUILD REQUIRED] {stage_name}: existing artifact failed spot check")
        if raise_on_failure:
            raise RuntimeError(f"Existing artifact spot check failed: {stage_name}") from exc
        return False
    _record_stage(state, stage_name, "completed", command, extra={"reused_existing_artifact": True})
    print(f"[REUSE] {stage_name}: existing artifact passed spot check")
    return True


def _record_stage(state, stage_name, status, command, extra=None):
    state.setdefault("stages", {})[stage_name] = {
        "status": status,
        "updated_at": _now(),
        "command": command,
        "extra": extra or {},
    }
    _save_state(state)


def _record_reused_stage(state, stage_name, command, *, dry_run, extra=None):
    if dry_run:
        return
    reuse_extra = {"reused_existing_artifact": True}
    reuse_extra.update(extra or {})
    _record_stage(state, stage_name, "completed", [str(item) for item in command], extra=reuse_extra)


def _invalidate_strategy_results(state):
    stages = state.setdefault("stages", {})
    invalidated = [
        name for name in list(stages)
        if (
            name.startswith("strategy_batch_")
            or name == "strategy_summary_finalize"
            or name == "decision_council_backtest"
            or name == "decision_council_ablations"
            or name == "decision_council_evaluation"
        )
    ]
    for name in invalidated:
        stages.pop(name, None)
    if invalidated:
        print("Invalidated completed strategy stages after feature rebuild:", invalidated)
        _save_state(state)


def _require_artifacts(paths):
    missing = [str(Path(path)) for path in paths if not Path(path).exists()]
    if missing:
        raise FileNotFoundError("Required published artifacts are missing:\n" + "\n".join(missing))


def _validate_interpreters():
    missing = [str(path) for path in [MAIN_PYTHON, EXTERNAL_DATA_PYTHON] if not path.exists()]
    if missing:
        raise FileNotFoundError("Required Python interpreters are missing:\n" + "\n".join(missing))


def _load_state():
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["workflow_version"] = "auto_complete_after_vpn_v2_decision_council"
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _print_header(args, state):
    print("========== Auto Complete After VPN ==========")
    print("Project:", PROJECT_DIR)
    print("Main Python:", MAIN_PYTHON)
    print("External-data Python:", EXTERNAL_DATA_PYTHON)
    print("Dry run:", args.dry_run)
    print("Local fast mode:", args.local_fast_mode)
    print("Strategy workers:", args.strategy_workers)
    strategy_window = window_identity(STRATEGY_START_DATE, STRATEGY_END_DATE)
    print(
        "Strategy date range:",
        f"{strategy_window['start_date'] or '-'} -> {strategy_window['end_date'] or '-'}",
    )
    if args.governance_start_date or args.governance_end_date:
        suffix = " (default local range)" if args.governance_date_range_defaulted else ""
        print(f"Governance date range: {args.governance_start_date or '-'} -> {args.governance_end_date or '-'}{suffix}")
    if args.governance_max_days is not None:
        print(f"Governance max days: {args.governance_max_days}")
    print("Recorded completed stages:", sum(1 for item in state.get("stages", {}).values() if item.get("status") == "completed"))
    print("=============================================")


def _format_command(command):
    return " ".join(f'"{item}"' if " " in item else item for item in command)


def _governance_code_signature():
    files = [
        "config.py",
        "run_governance_backtest.py",
        "run_governance_industrial_pipeline.py",
        "evaluate_governance_results.py",
        "functions/decision_council/engine.py",
        "functions/decision_council/runner.py",
        "functions/decision_council/policy.py",
        "functions/decision_council/plots.py",
        "functions/decision_council/safety.py",
        "functions/decision_council/pending_orders.py",
        "functions/decision_council/accounting.py",
        "functions/decision_council/account_state.py",
        "functions/decision_council/alpha.py",
        "functions/decision_council/proposals.py",
        "functions/decision_council/advanced_policies.py",
        "functions/decision_council/evaluation.py",
        "functions/decision_council/industrial_pipeline.py",
        "functions/decision_council/institutional_rewards.py",
        "functions/decision_council/monitoring.py",
        "functions/execution/cost_model.py",
        "functions/execution/corporate_action_ledger.py",
    ]
    return build_signature([code_file_fingerprint(path) for path in files])


def _strategy_code_signature():
    files = [
        "config.py",
        "run_strategy_batches.py",
        "run_precomputed_technical_strategies.py",
        "finalize_strategy_batch_summary.py",
        "verify_mainline_outputs.py",
        "functions/feature_engineering.py",
        "functions/position_managed_selection.py",
        "functions/strategy_registry.py",
        "functions/strategy_selection.py",
        "functions/strategy_signal_generators.py",
        "functions/strategy_params.py",
        "functions/backtest_engine.py",
        "functions/metrics.py",
        "functions/report_builder.py",
    ]
    return build_signature([code_file_fingerprint(path) for path in files])


def _now():
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def _single_instance_lock():
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock_file = LOCK_PATH.open("a+", encoding="utf-8")
    except PermissionError as exc:
        raise RuntimeError(
            "Another automatic completion run is already active. "
            "Stop the previous Spyder run before starting a new one."
        ) from exc
    try:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(" ")
            lock_file.flush()
        lock_file.seek(0)
        try:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError(
                "Another automatic completion run is already active. "
                "Stop the previous Spyder run before starting a new one."
            ) from exc
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(f"pid={os.getpid()} started_at={_now()}\n")
        lock_file.flush()
        lock_file.seek(0)
        yield
    finally:
        try:
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        lock_file.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nAUTO COMPLETION STOPPED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
