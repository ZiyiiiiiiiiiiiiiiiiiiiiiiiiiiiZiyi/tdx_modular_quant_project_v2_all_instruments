"""Verify browser monitor startup and restart without opening a real browser."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import functions.decision_council.live_monitor as module


class _FakeProcess:
    def __init__(self):
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0


def main() -> int:
    original_tempdir = module.tempfile.gettempdir
    original_popen = module.subprocess.Popen
    processes: list[_FakeProcess] = []
    with tempfile.TemporaryDirectory() as directory:
        state_dir = Path(directory) / "tdx_governance_live_monitor"
        state_dir.mkdir(parents=True)
        state_path = state_dir / f"monitor_state_{os.getpid()}.json"
        state_path.write_text(json.dumps({"command": "close"}), encoding="utf-8")

        def _fake_popen(*args, **kwargs):
            process = _FakeProcess()
            processes.append(process)
            return process

        module.tempfile.gettempdir = lambda: directory
        module.subprocess.Popen = _fake_popen
        try:
            monitor = module.GovernanceLiveMonitor(total_days=5, initial_nav=20_000)
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            assert payload["command"] == "idle", payload
            assert monitor.available

            monitor.start_session(title="test", total_days=5, initial_nav=20_000)
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            assert payload["command"] == "session", payload

            processes[-1].returncode = 1
            monitor.update(
                date="2023-01-04",
                exposure={"nominal_nav": 20_000, "liquidatable_nav": 20_000},
                day_index=0,
            )
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            assert payload["command"] == "update", payload
            assert len(processes) == 2, len(processes)
            assert monitor.available
        finally:
            module.tempfile.gettempdir = original_tempdir
            module.subprocess.Popen = original_popen

    print("[PASS] live monitor clears stale close command and restarts a dead browser process")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
