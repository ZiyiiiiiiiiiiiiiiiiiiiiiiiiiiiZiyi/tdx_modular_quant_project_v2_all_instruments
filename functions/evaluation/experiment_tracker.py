# -*- coding: utf-8 -*-
import json
import subprocess
from datetime import datetime
from pathlib import Path

from config import RUNS_DIR, RUN_ID_PREFIX, RUN_METADATA_FILENAME
from functions.pipeline_cache import code_file_fingerprint, file_fingerprint


def build_run_id(prefix=RUN_ID_PREFIX):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return f"{prefix}_{timestamp}"


def start_experiment_run(
    run_id=None,
    config_snapshot=None,
    tracked_inputs=None,
    extra=None,
):
    run_id = run_id or build_run_id()
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    metadata = {
        "run_id": run_id,
        "status": "running",
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "cwd": str(Path.cwd()),
        "config_snapshot": config_snapshot or {},
        "tracked_inputs": _fingerprint_inputs(tracked_inputs or []),
        "code_snapshot": _default_code_snapshot(),
        "git_commit": _git_commit_hash(),
    }
    if extra:
        metadata["extra"] = extra

    write_run_metadata(run_dir, metadata)
    return run_id, run_dir, metadata


def mark_run_completed(run_dir, extra=None):
    metadata = read_run_metadata(run_dir)
    metadata["status"] = "completed"
    metadata["completed_at"] = datetime.now().isoformat(timespec="seconds")
    if extra:
        metadata["completion"] = extra
    write_run_metadata(run_dir, metadata)
    return metadata


def mark_run_failed(run_dir, error_message):
    metadata = read_run_metadata(run_dir)
    metadata["status"] = "failed"
    metadata["failed_at"] = datetime.now().isoformat(timespec="seconds")
    metadata["error_message"] = str(error_message)
    write_run_metadata(run_dir, metadata)
    return metadata


def read_run_metadata(run_dir):
    metadata_path = Path(run_dir) / RUN_METADATA_FILENAME
    if not metadata_path.exists():
        return {}
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def write_run_metadata(run_dir, metadata):
    metadata_path = Path(run_dir) / RUN_METADATA_FILENAME
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _fingerprint_inputs(paths):
    fingerprints = []
    for path in paths:
        fingerprints.append(file_fingerprint(path))
    return fingerprints


def _default_code_snapshot():
    tracked_files = [
        "main.py",
        "config.py",
        "functions/feature_engineering.py",
        "functions/strategy_registry.py",
    ]
    return [code_file_fingerprint(path) for path in tracked_files]


def _git_commit_hash():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
