"""Lightweight runtime progress reporting for the browser launcher."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import time

from config import RESULT_DIR


PROGRESS_JSON = Path(RESULT_DIR) / "runtime_progress.json"


def reset_progress(*, task_name: str, total: int | None = None, message: str = "starting") -> None:
    now = time.time()
    write_progress(
        task_name=task_name,
        status="running",
        percent=0.0,
        current=0,
        total=total,
        step="start",
        message=message,
        started_at=now,
    )


def complete_progress(*, task_name: str, message: str = "complete") -> None:
    existing = read_progress()
    write_progress(
        task_name=task_name,
        status="complete",
        percent=100.0,
        current=existing.get("total") or existing.get("current") or 0,
        total=existing.get("total"),
        step="complete",
        message=message,
        started_at=existing.get("started_at"),
    )


def fail_progress(*, task_name: str, message: str) -> None:
    existing = read_progress()
    write_progress(
        task_name=task_name,
        status="failed",
        percent=existing.get("percent", 0.0),
        current=existing.get("current"),
        total=existing.get("total"),
        step="failed",
        message=message,
        started_at=existing.get("started_at"),
    )


def write_progress(
    *,
    task_name: str,
    status: str = "running",
    percent: float = 0.0,
    current: int | None = None,
    total: int | None = None,
    step: str = "",
    message: str = "",
    detail: str = "",
    started_at: float | None = None,
) -> None:
    started = float(started_at or read_progress().get("started_at") or time.time())
    now = time.time()
    bounded_percent = min(max(float(percent), 0.0), 100.0)
    elapsed = max(now - started, 0.0)
    eta = None
    if status == "running" and bounded_percent > 0.0:
        eta = max(elapsed * (100.0 - bounded_percent) / bounded_percent, 0.0)
    payload = {
        "task_name": str(task_name),
        "status": str(status),
        "percent": round(bounded_percent, 2),
        "current": int(current) if current is not None else None,
        "total": int(total) if total is not None else None,
        "step": str(step),
        "message": str(message),
        "detail": str(detail),
        "started_at": started,
        "started_at_text": datetime.fromtimestamp(started).strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": now,
        "updated_at_text": datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_seconds": round(elapsed, 1),
        "eta_seconds": round(eta, 1) if eta is not None else None,
    }
    PROGRESS_JSON.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = PROGRESS_JSON.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(PROGRESS_JSON)


def read_progress() -> dict:
    if not PROGRESS_JSON.exists():
        return {
            "task_name": "",
            "status": "idle",
            "percent": 0.0,
            "message": "no task has reported progress yet",
        }
    try:
        return json.loads(PROGRESS_JSON.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "task_name": "",
            "status": "unknown",
            "percent": 0.0,
            "message": f"progress read failed: {exc}",
        }
