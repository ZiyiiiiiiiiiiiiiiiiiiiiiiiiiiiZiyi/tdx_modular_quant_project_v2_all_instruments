import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from functions import runtime_progress


def main() -> int:
    original_path = runtime_progress.PROGRESS_JSON
    try:
        with TemporaryDirectory() as temporary:
            runtime_progress.PROGRESS_JSON = Path(temporary) / "runtime_progress.json"
            runtime_progress.reset_progress(task_name="owned_task", total=3, message="owned")
            owner_pid = os.getpid()
            owned = runtime_progress.read_progress(owner_pid=owner_pid)
            assert owned["task_name"] == "owned_task"
            assert owned["owner_pid"] == owner_pid

            runtime_progress.PROGRESS_JSON.write_text(json.dumps({
                "task_name": "foreign_task",
                "owner_pid": owner_pid + 1,
                "status": "complete",
            }), encoding="utf-8")
            owned_after_foreign_write = runtime_progress.read_progress(owner_pid=owner_pid)
            assert owned_after_foreign_write["task_name"] == "owned_task"
            assert owned_after_foreign_write["status"] == "running"

            sleeper = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                assert runtime_progress._pid_alive(sleeper.pid) is True
                assert sleeper.poll() is None, "PID health probe must not terminate its target"
            finally:
                sleeper.terminate()
                sleeper.wait(timeout=10)
    finally:
        runtime_progress.PROGRESS_JSON = original_path
        runtime_progress.clear_progress_context()
    print("[PASS] PID-owned progress is isolated from the compatibility mirror")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
