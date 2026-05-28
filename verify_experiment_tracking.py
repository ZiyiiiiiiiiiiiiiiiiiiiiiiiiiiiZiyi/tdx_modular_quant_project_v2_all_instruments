# -*- coding: utf-8 -*-
from pathlib import Path

from config import RUNS_DIR
from functions.evaluation.experiment_tracker import read_run_metadata


REQUIRED_METADATA_KEYS = {
    "run_id",
    "status",
    "started_at",
    "cwd",
    "config_snapshot",
    "tracked_inputs",
    "code_snapshot",
    "git_commit",
}


def verify_experiment_tracking():
    failures: list[str] = []

    print("=== Verify experiment tracking ===")
    if not RUNS_DIR.exists():
        failures.append(f"runs dir missing: {RUNS_DIR}")
        print(f"[FAIL] runs dir missing: {RUNS_DIR}")
    else:
        print(f"[PASS] runs dir exists: {RUNS_DIR}")

    run_dirs = sorted(
        [path for path in RUNS_DIR.iterdir() if path.is_dir()],
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    if not run_dirs:
        failures.append("no run directories found")
        print("[FAIL] no run directories found")
    else:
        print(f"[PASS] found run directories: {len(run_dirs)}")

    if run_dirs:
        latest_run = run_dirs[0]
        metadata = read_run_metadata(latest_run)
        print(f"Latest run: {latest_run}")

        missing_keys = sorted(REQUIRED_METADATA_KEYS - set(metadata))
        if missing_keys:
            failures.append(f"latest run missing metadata keys: {missing_keys}")
            print(f"[FAIL] latest run missing metadata keys: {missing_keys}")
        else:
            print("[PASS] latest run metadata keys present")

        status = metadata.get("status")
        if status not in {"running", "completed", "failed"}:
            failures.append(f"unexpected latest run status: {status}")
            print(f"[FAIL] unexpected latest run status: {status}")
        else:
            print(f"[PASS] latest run status valid: {status}")

        tracked_inputs = metadata.get("tracked_inputs", [])
        if not isinstance(tracked_inputs, list):
            failures.append("tracked_inputs is not a list")
            print("[FAIL] tracked_inputs is not a list")
        elif not tracked_inputs:
            failures.append("tracked_inputs is empty")
            print("[FAIL] tracked_inputs is empty")
        else:
            print(f"[PASS] tracked_inputs count: {len(tracked_inputs)}")

        code_snapshot = metadata.get("code_snapshot", [])
        if not isinstance(code_snapshot, list):
            failures.append("code_snapshot is not a list")
            print("[FAIL] code_snapshot is not a list")
        elif not code_snapshot:
            failures.append("code_snapshot is empty")
            print("[FAIL] code_snapshot is empty")
        else:
            print(f"[PASS] code_snapshot count: {len(code_snapshot)}")

        if status == "completed" and "completed_at" not in metadata:
            failures.append("completed run missing completed_at")
            print("[FAIL] completed run missing completed_at")
        elif status == "completed":
            print("[PASS] completed run has completed_at")

        if status == "failed" and "error_message" not in metadata:
            failures.append("failed run missing error_message")
            print("[FAIL] failed run missing error_message")
        elif status == "failed":
            print("[PASS] failed run has error_message")

    print()
    if failures:
        print("Experiment tracking verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Experiment tracking verification passed.")


if __name__ == "__main__":
    verify_experiment_tracking()
