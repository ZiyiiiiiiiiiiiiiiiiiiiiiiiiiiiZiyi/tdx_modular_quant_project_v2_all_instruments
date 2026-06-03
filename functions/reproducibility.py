# -*- coding: utf-8 -*-
"""First-version reproducibility manifest with fingerprints and review slots."""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from datetime import datetime
from pathlib import Path

from config import (
    ADJUSTMENT_FACTORS_PARQUET,
    CLEAN_DAILY_PARQUET,
    CORPORATE_ACTIONS_PARQUET,
    FEATURE_DAILY_PARQUET,
    FORMAL_MANIFEST_JSON,
    MARKET_CAP_PARQUET,
    RAW_DAILY_PARQUET,
)
from functions.execution.execution_model import execution_model_snapshot


def build_reproducibility_manifest():
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "python_version": platform.python_version(),
        "git_commit": _git_commit(),
        "one_click_command": '& "E:\\ForANACONDA\\python.exe" spyder_run_all_low_memory.py',
        "transform_version": "p0_exploratory_engine_v2",
        "execution_model": execution_model_snapshot(),
        "inputs": {
            "raw_daily": _fingerprint(RAW_DAILY_PARQUET),
            "clean_daily": _fingerprint(CLEAN_DAILY_PARQUET),
            "features": _fingerprint(FEATURE_DAILY_PARQUET),
            "corporate_actions": _fingerprint(CORPORATE_ACTIONS_PARQUET),
            "adjustment_factors": _fingerprint(ADJUSTMENT_FACTORS_PARQUET),
            "market_cap": _fingerprint(MARKET_CAP_PARQUET),
        },
        "code_files": {
            path: _fingerprint(path)
            for path in [
                "config.py",
                "main.py",
                "functions/backtest_engine.py",
                "functions/feature_engineering.py",
                "functions/governance.py",
            ]
        },
        "review_signature": "",
        "review_timestamp": "",
        "manifest_hash": "",
    }
    payload["manifest_hash"] = _payload_hash(payload)
    return payload


def save_reproducibility_manifest(output_path=FORMAL_MANIFEST_JSON):
    payload = build_reproducibility_manifest()
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _fingerprint(path):
    file_path = Path(path)
    if not file_path.exists():
        return {"path": str(file_path), "exists": False, "size": 0, "sha256": ""}
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return {"path": str(file_path), "exists": True, "size": file_path.stat().st_size, "sha256": digest.hexdigest()}


def _payload_hash(payload):
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
