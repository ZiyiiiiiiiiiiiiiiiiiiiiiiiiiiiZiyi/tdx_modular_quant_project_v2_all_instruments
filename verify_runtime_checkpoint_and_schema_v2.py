"""Runtime heartbeat, completion and stable empty-schema contracts."""
from __future__ import annotations

from pathlib import Path
import tempfile

import pandas as pd

from functions.decision_council.outputs import write_governance_csv
from functions.decision_council.runtime_checkpoint import (
    read_run_checkpoint,
    write_run_checkpoint,
)
from functions.decision_council.artifact_manifest import update_artifact_manifest


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = write_governance_csv(pd.DataFrame(), root / "empty.csv")
        header = path.read_text(encoding="utf-8-sig").splitlines()[0]
        assert header == "artifact_status,schema_version,status_reason"
        print("[PASS] zero-column artifacts retain a readable stable header")

        write_run_checkpoint(
            root,
            status="running",
            current_day=3,
            total_days=20,
            last_successful_date="2025-01-06",
            runtime_identity_hash="abc",
            stage="date_complete",
        )
        checkpoint = read_run_checkpoint(root)
        assert checkpoint["percent"] == 15.0
        assert checkpoint["last_successful_date"] == "2025-01-06"
        assert checkpoint["is_stale"] is False
        print("[PASS] heartbeat exposes date, stage, identity and freshness")

        write_run_checkpoint(
            root,
            status="interrupted",
            current_day=4,
            total_days=20,
            last_successful_date="2025-01-07",
            runtime_identity_hash="abc",
            stage="keyboard_interrupt",
            error="KeyboardInterrupt: user requested Ctrl+C stop",
        )
        interrupted = read_run_checkpoint(root)
        assert interrupted["status"] == "interrupted"
        assert interrupted["stage"] == "keyboard_interrupt"
        assert interrupted["current_day"] == 4
        assert interrupted["last_successful_date"] == "2025-01-07"
        assert interrupted["is_stale"] is False
        print("[PASS] Ctrl+C interruption preserves an explicit non-stale checkpoint")

        update_artifact_manifest(
            root,
            stage="core_ledgers_saved",
            status="saving",
            core_complete=True,
            artifact_name="governance_daily_result",
            artifact_status="complete",
        )
        update_artifact_manifest(
            root,
            stage="save_failed",
            status="failed",
            error="injected audit failure",
        )
        manifest = __import__("json").loads(
            (root / "artifact_manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["core_complete"] is True
        assert manifest["audit_complete"] is False
        assert manifest["status"] == "failed"
        assert manifest["error"] == "injected audit failure"
        for index in range(50):
            update_artifact_manifest(
                root,
                stage=f"rapid_stage_{index}",
                status="saving",
            )
        assert not list(root.glob("*.tmp"))
        print("[PASS] artifact manifest preserves core completion and rapid atomic updates")


if __name__ == "__main__":
    main()
