# -*- coding: utf-8 -*-
"""Resume external data and rebuild every derived artifact after VPN is disabled.

This is the user-facing one-click completion entry point. It is intentionally
restartable: successful stages and strategy batches are recorded in a JSON
state file, while provider fetchers keep their own staged resume files.
"""
from __future__ import annotations

import argparse
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
    CORPORATE_ACTIONS_PARQUET,
    MARKET_CAP_PARQUET,
    REPORT_DIR,
)
from functions.strategy_registry import list_strategy_names
from functions.pipeline_cache import build_signature, code_file_fingerprint


PROJECT_DIR = Path(__file__).resolve().parent
MAIN_PYTHON = Path(r"E:\ForANACONDA\python.exe")
EXTERNAL_DATA_PYTHON = Path(r"C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe")
STATE_PATH = REPORT_DIR / "auto_complete_after_vpn_state.json"
LOCK_PATH = REPORT_DIR / "auto_complete_after_vpn.lock"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print the workflow without running commands.")
    parser.add_argument("--reset-state", action="store_true", help="Discard recorded stage progress and rerun all stages.")
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
    parser.add_argument("--skip-governance", action="store_true", help="Do not run the daily decision-council backtest.")
    parser.add_argument("--skip-governance-ablations", action="store_true", help="Skip equal-weight governance baseline and ablation backtests.")
    parser.add_argument("--governance-start-date", default=None, help="Optional first governance backtest date.")
    parser.add_argument("--governance-end-date", default=None, help="Optional last governance backtest date.")
    parser.add_argument("--governance-max-days", type=int, default=None, help="Optional governance smoke-run limit.")
    parser.add_argument(
        "--safety-proxy-mode",
        choices=["strict", "degraded_backtest"],
        default="strict",
        help="Use strict mode for normal one-click runs; degraded mode is exploratory only.",
    )
    parser.add_argument("--batch-size", type=int, default=1, help="Strategies per fresh subprocess. Use 1 on low-memory machines.")
    parser.add_argument("--start-batch-index", type=int, default=0, help="Start strategy rerun from this zero-based batch.")
    return parser.parse_args()


def main():
    with _single_instance_lock():
        _run_workflow()


def _run_workflow():
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
                "50",
                "--dividend-batch-size",
                "5",
                "--request-delay-seconds",
                "0.6",
                "--batch-delay-seconds",
                "3",
                "--login-retries",
                "5",
                "--login-retry-delay-seconds",
                "8",
                "--socket-timeout-seconds",
                "30",
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
            "tdx_finance",
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

    if not args.skip_strategy_rerun:
        _run_strategy_batches(state, args, dry_run=args.dry_run)
        _run_stage(
            state,
            "strategy_summary_finalize",
            [MAIN_PYTHON, "finalize_strategy_batch_summary.py"],
            dry_run=args.dry_run,
        )

    if not args.skip_governance:
        _run_stage(
            state,
            "decision_council_industrial_build",
            [MAIN_PYTHON, "run_governance_industrial_pipeline.py"],
            dry_run=args.dry_run,
            extra={"governance_code_signature": _governance_code_signature()},
        )
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
        _run_stage(
            state,
            "decision_council_backtest",
            governance_command,
            dry_run=args.dry_run,
            extra={"governance_code_signature": _governance_code_signature()},
        )
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
        if not args.skip_governance_ablations:
            ablation_command = [
                MAIN_PYTHON,
                "run_governance_ablations.py",
                "--safety-proxy-mode",
                args.safety_proxy_mode,
            ]
            if args.governance_start_date:
                ablation_command.extend(["--start-date", args.governance_start_date])
            if args.governance_end_date:
                ablation_command.extend(["--end-date", args.governance_end_date])
            if args.governance_max_days is not None:
                ablation_command.extend(["--max-days", str(args.governance_max_days)])
            _run_stage(
                state,
                "decision_council_ablations",
                ablation_command,
                dry_run=args.dry_run,
                extra={"governance_code_signature": _governance_code_signature()},
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
    for batch_index in range(max(args.start_batch_index, 0), batch_count):
        batch_names = names[batch_index * batch_size:(batch_index + 1) * batch_size]
        stage_name = f"strategy_batch_{batch_index:03d}"
        _run_stage(
            state,
            stage_name,
            [
                MAIN_PYTHON,
                "run_strategy_batches.py",
                "--mode",
                "all",
                "--batch-size",
                str(batch_size),
                "--batch-index",
                str(batch_index),
            ],
            dry_run=dry_run,
            extra={"strategy_names": batch_names},
        )


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
        child_env = os.environ.copy()
        child_env["PYTHONUNBUFFERED"] = "1"
        subprocess.run(command, cwd=PROJECT_DIR, check=True, env=child_env)
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
    print("Recorded completed stages:", sum(1 for item in state.get("stages", {}).values() if item.get("status") == "completed"))
    print("=============================================")


def _format_command(command):
    return " ".join(f'"{item}"' if " " in item else item for item in command)


def _governance_code_signature():
    files = [
        "config.py",
        "run_governance_backtest.py",
        "run_governance_industrial_pipeline.py",
        "run_governance_ablations.py",
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
