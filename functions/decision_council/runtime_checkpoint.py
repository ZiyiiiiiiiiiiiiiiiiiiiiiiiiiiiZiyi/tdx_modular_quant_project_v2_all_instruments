"""Atomic governance heartbeat/checkpoint metadata.

The file is an observability and restart-audit contract. It intentionally does
not pretend that a partially serialized strategy object is safe to resume.
"""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import time


CHECKPOINT_SCHEMA_VERSION = "governance_checkpoint_v1"


def write_run_checkpoint(
    output_dir,
    *,
    status: str,
    current_day: int,
    total_days: int,
    last_successful_date=None,
    runtime_identity_hash: str = "",
    stage: str = "",
    error: str = "",
) -> Path:
    target = Path(output_dir) / "run_checkpoint.json"
    now = time.time()
    payload = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "status": str(status),
        "stage": str(stage),
        "current_day": int(current_day),
        "total_days": int(total_days),
        "percent": (
            round(100.0 * int(current_day) / max(int(total_days), 1), 2)
            if total_days
            else 0.0
        ),
        "last_successful_date": (
            str(last_successful_date) if last_successful_date is not None else None
        ),
        "runtime_identity_hash": str(runtime_identity_hash),
        "owner_pid": os.getpid(),
        "heartbeat_at": now,
        "heartbeat_at_text": datetime.fromtimestamp(now).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "error": str(error),
        "resume_mode": "audit_checkpoint_only_fail_closed",
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(
        f"{target.stem}_{os.getpid()}_{time.time_ns()}.tmp"
    )
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(target)
    return target


def read_run_checkpoint(output_dir, *, stale_after_seconds: float = 120.0) -> dict:
    target = Path(output_dir) / "run_checkpoint.json"
    if not target.exists():
        return {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "status": "missing",
            "is_stale": True,
        }
    payload = json.loads(target.read_text(encoding="utf-8"))
    age = max(time.time() - float(payload.get("heartbeat_at", 0.0)), 0.0)
    payload["freshness_seconds"] = round(age, 1)
    payload["is_stale"] = (
        str(payload.get("status")) == "running"
        and age > float(stale_after_seconds)
    )
    return payload
