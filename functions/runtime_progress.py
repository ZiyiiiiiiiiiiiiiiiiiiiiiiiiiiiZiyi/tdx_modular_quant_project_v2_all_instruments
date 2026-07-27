"""Lightweight runtime progress reporting for the browser launcher."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import time

from config import RESULT_DIR


PROGRESS_JSON = Path(RESULT_DIR) / "runtime_progress.json"
_PROGRESS_CONTEXT: dict = {}


def set_progress_context(*, parent_task_name: str, task_index: int, task_total: int) -> None:
    """Map nested task progress into one stable parent progress stream."""
    existing = read_progress(owner_pid=os.getpid())
    _PROGRESS_CONTEXT.clear()
    _PROGRESS_CONTEXT.update(
        {
            "parent_task_name": str(parent_task_name),
            "task_index": max(int(task_index), 1),
            "task_total": max(int(task_total), 1),
            "started_at": existing.get("started_at") or time.time(),
        }
    )


def clear_progress_context() -> None:
    _PROGRESS_CONTEXT.clear()


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
    existing = read_progress(owner_pid=os.getpid())
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
    existing = read_progress(owner_pid=os.getpid())
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
    child_payload = None
    if _PROGRESS_CONTEXT and str(task_name) != _PROGRESS_CONTEXT["parent_task_name"]:
        child_percent = min(max(float(percent), 0.0), 100.0)
        task_index = int(_PROGRESS_CONTEXT["task_index"])
        task_total = int(_PROGRESS_CONTEXT["task_total"])
        child_payload = {
            "child_task_name": str(task_name),
            "child_status": str(status),
            "child_percent": round(child_percent, 2),
            "child_current": int(current) if current is not None else None,
            "child_total": int(total) if total is not None else None,
        }
        task_name = _PROGRESS_CONTEXT["parent_task_name"]
        status = "running"
        percent = ((task_index - 1) + child_percent / 100.0) / task_total * 100.0
        current = task_index
        total = task_total
        started_at = _PROGRESS_CONTEXT["started_at"]

    owner_pid = os.getpid()
    started = float(started_at or read_progress(owner_pid=owner_pid).get("started_at") or time.time())
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
        "owner_pid": owner_pid,
        **(child_payload or {}),
    }
    PROGRESS_JSON.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, indent=2)
    owner_path = PROGRESS_JSON.with_name(f"{PROGRESS_JSON.stem}_{owner_pid}{PROGRESS_JSON.suffix}")
    _atomic_write_progress(owner_path, data)
    _atomic_write_progress(PROGRESS_JSON, data)


def _atomic_write_progress(target_path: Path, data: str) -> None:
    last_error = None
    for attempt in range(8):
        tmp_path = target_path.with_name(
            f"{target_path.stem}_{os.getpid()}_{time.time_ns()}_{attempt}.tmp"
        )
        try:
            tmp_path.write_text(data, encoding="utf-8")
            tmp_path.replace(target_path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.03 * (attempt + 1))
        except OSError as exc:
            last_error = exc
            time.sleep(0.03 * (attempt + 1))
        finally:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
    print(f"[WARN] runtime progress write skipped for {target_path} after retries: {last_error}", flush=True)


def read_progress(*, owner_pid: int | None = None) -> dict:
    progress_path = (
        PROGRESS_JSON.with_name(f"{PROGRESS_JSON.stem}_{int(owner_pid)}{PROGRESS_JSON.suffix}")
        if owner_pid is not None else PROGRESS_JSON
    )
    if not progress_path.exists():
        return {
            "task_name": "",
            "status": "idle",
            "percent": 0.0,
            "message": "no task has reported progress yet",
        }
    try:
        payload = json.loads(progress_path.read_text(encoding="utf-8"))
        if owner_pid is not None and int(payload.get("owner_pid", -1)) != int(owner_pid):
            raise ValueError(f"progress owner mismatch for pid={owner_pid}")
        now = time.time()
        age = max(now - float(payload.get("updated_at", 0.0) or 0.0), 0.0)
        payload["freshness_seconds"] = round(age, 1)
        payload["is_stale"] = (
            str(payload.get("status", "")).lower() == "running" and age > 120.0
        )
        payload["owner_pid_alive"] = _pid_alive(payload.get("owner_pid"))
        if payload["is_stale"]:
            payload["display_status"] = "stale"
        elif (
            str(payload.get("status", "")).lower() == "running"
            and payload["owner_pid_alive"] is False
        ):
            payload["display_status"] = "orphaned"
        else:
            payload["display_status"] = str(payload.get("status", "unknown"))
        return payload
    except Exception as exc:
        return {
            "task_name": "",
            "status": "unknown",
            "percent": 0.0,
            "message": f"progress read failed: {exc}",
        }


def _pid_alive(pid) -> bool | None:
    try:
        process_id = int(pid)
    except (TypeError, ValueError):
        return None
    if process_id <= 0:
        return False
    if process_id == os.getpid():
        return True
    if os.name == "nt":
        # os.kill(pid, 0) is a harmless existence probe on POSIX. On Windows
        # Python routes it through TerminateProcess, so it can terminate the
        # very worker whose health we are checking. Query a process handle
        # instead and never signal the target.
        import ctypes

        process_query_limited_information = 0x1000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            process_id,
        )
        if handle:
            exit_code = ctypes.c_ulong()
            queried = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            kernel32.CloseHandle(handle)
            return bool(queried) and int(exit_code.value) == 259
        return ctypes.get_last_error() == 5
    try:
        os.kill(process_id, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False
