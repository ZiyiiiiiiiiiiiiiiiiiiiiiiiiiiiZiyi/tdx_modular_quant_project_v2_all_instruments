"""Atomic governance heartbeat/checkpoint metadata.

The file is an observability and restart-audit contract. It intentionally does
not pretend that a partially serialized strategy object is safe to resume.
"""
from __future__ import annotations

from datetime import datetime
import json
import math
import os
from pathlib import Path
import time


CHECKPOINT_SCHEMA_VERSION = "governance_checkpoint_v1"
DAILY_SNAPSHOT_SCHEMA_VERSION = "governance_daily_atomic_snapshot_v1"


def _json_safe(value):
    """Convert pandas/numpy/date values without importing the strategy stack."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    # pandas.NA raises on bool conversion; its string form is stable enough for
    # a diagnostic snapshot and never becomes a fabricated numeric zero.
    return str(value)


def _atomic_write_json(target: Path, payload: dict) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(
        f"{target.stem}_{os.getpid()}_{time.time_ns()}.tmp"
    )
    temporary.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    last_error = None
    for attempt in range(20):
        try:
            os.replace(temporary, target)
            last_error = None
            break
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.05 * (attempt + 1))
    if last_error is not None:
        raise last_error
    return target


def write_daily_atomic_snapshot(
    output_dir,
    *,
    trading_day_index: int,
    trade_date,
    runtime_identity_hash: str,
    payload: dict,
) -> Path:
    """Persist one immutable completed-day audit snapshot plus latest pointer."""
    day_number = max(int(trading_day_index), 1)
    body = {
        "schema_version": DAILY_SNAPSHOT_SCHEMA_VERSION,
        "trading_day_index": day_number,
        "trade_date": str(trade_date),
        "runtime_identity_hash": str(runtime_identity_hash),
        "owner_pid": os.getpid(),
        "written_at": time.time(),
        **dict(payload or {}),
    }
    snapshot = (
        Path(output_dir)
        / "daily_checkpoints"
        / f"day_{day_number:04d}_{str(trade_date)}.json"
    )
    _atomic_write_json(snapshot, body)
    _atomic_write_json(Path(output_dir) / "latest_daily_snapshot.json", body)
    return snapshot


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
    return _atomic_write_json(target, payload)


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
