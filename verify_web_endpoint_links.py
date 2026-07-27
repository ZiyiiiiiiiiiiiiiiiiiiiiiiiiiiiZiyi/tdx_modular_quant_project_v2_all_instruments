"""Live localhost endpoint and link verification for the Web launcher."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        state = Path(temporary) / "selection.json"
        environment = dict(os.environ)
        environment["TDX_WEB_NO_BROWSER"] = "1"
        process = subprocess.Popen(
            [sys.executable, "-u", "main_launcher_web.py", str(state)],
            cwd=Path(__file__).resolve().parent,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            base = ""
            deadline = time.time() + 20.0
            while time.time() < deadline and process.poll() is None:
                line = process.stdout.readline() if process.stdout is not None else ""
                match = re.search(r"(http://127\.0\.0\.1:\d+)/run", line)
                if match:
                    base = match.group(1)
                    break
            check(bool(base), "launcher binds a discoverable localhost port")
            with urlopen(base + "/api/health", timeout=10) as response:
                health = json.loads(response.read().decode("utf-8"))
            check(health["status"] == "ok" and health["run_path"] == "/run", "health endpoint matches the run route")
            for path, marker in (("/run", "strategy_logic_version"), ("/results", "/api/results")):
                with urlopen(base + path, timeout=10) as response:
                    body = response.read().decode("utf-8")
                check(response.status == 200 and marker in body, f"{path} link resolves to its product page")
            payload = json.dumps({
                "tasks": ["pit_level1_audit"],
                "profile": "full",
                "governance": {"validation_window_preset": "custom", "max_days": ""},
            }).encode("utf-8")
            request = Request(
                base + "/submit",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=10) as response:
                submitted = json.loads(response.read().decode("utf-8"))
            check(response.status == 200 and state.exists(), "submit route writes a validated selection payload")
            check("message" in submitted, "submit route returns a JSON product response")
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
    print("[PASS] Web endpoint/link verification completed")


if __name__ == "__main__":
    main()
