"""Verify that a browser submission outlives the Spyder/main.py host process."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from urllib.request import Request, urlopen


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def _terminate_pid(pid: int) -> None:
    if pid <= 0:
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


def main() -> int:
    environment = dict(os.environ)
    environment["TDX_WEB_NO_BROWSER"] = "1"
    # Product runs default to a visible Ctrl+C-capable console. This automated
    # test retains logged background mode so it can assert diagnostic paths.
    environment["TDX_WEB_VISIBLE_WORKER_CONSOLE"] = "0"
    host = subprocess.Popen(
        [sys.executable, "-u", "main.py"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    launcher_pid = 0
    worker_pid = 0
    try:
        base_url = ""
        deadline = time.time() + 30.0
        while time.time() < deadline and host.poll() is None:
            line = host.stdout.readline() if host.stdout is not None else ""
            match = re.search(r"(http://127\.0\.0\.1:\d+)/run", line)
            if match:
                base_url = match.group(1)
                break
        check(bool(base_url), "main.py launches the browser service")

        payload = json.dumps(
            {
                "tasks": [],
                "profile": "full",
                "governance": {
                    "validation_window_preset": "custom",
                    "max_days": "",
                },
            }
        ).encode("utf-8")
        request = Request(
            base_url + "/submit",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=15) as response:
            submitted = json.loads(response.read().decode("utf-8"))
        worker_pid = int(submitted["worker_pid"])
        check(worker_pid > 0 and worker_pid != host.pid, "submission creates a separate worker PID")

        host.wait(timeout=20)
        check(host.returncode == 0, "Spyder/main.py host returns after worker handoff")

        with urlopen(base_url + "/api/health", timeout=10) as response:
            health = json.loads(response.read().decode("utf-8"))
        launcher_pid = int(health["launcher_pid"])
        check(
            health["worker_mode"] is True and int(health["worker_pid"]) == worker_pid,
            "launcher remains bound to the delegated worker",
        )
        check(launcher_pid != host.pid, "browser launcher survives host exit")

        progress = {}
        deadline = time.time() + 15.0
        while time.time() < deadline:
            with urlopen(base_url + "/api/progress", timeout=10) as response:
                progress = json.loads(response.read().decode("utf-8"))
            if str(progress.get("status", "")).lower() == "failed":
                break
            time.sleep(0.2)
        check(
            str(progress.get("status", "")).lower() == "failed"
            and progress.get("owner_pid_alive") is False,
            "worker exit without a completion marker is exposed as FAILED",
        )
        check(
            str(progress.get("worker_stderr_path", "")).endswith(".stderr.log"),
            "failure response exposes the worker diagnostic log",
        )
    finally:
        if worker_pid:
            _terminate_pid(worker_pid)
        if launcher_pid:
            _terminate_pid(launcher_pid)
        if host.poll() is None:
            host.terminate()
            try:
                host.wait(timeout=10)
            except subprocess.TimeoutExpired:
                host.kill()
                host.wait(timeout=10)
    print("[PASS] interactive worker isolation verification completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
