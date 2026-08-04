"""Verify bounded retry for transient Windows checkpoint replacement locks."""
from pathlib import Path
from unittest.mock import patch

from functions.decision_council.runtime_checkpoint import write_run_checkpoint


def main():
    calls = []

    def replace_with_transient_lock(source, target):
        calls.append((source, target))
        if len(calls) < 3:
            raise PermissionError("transient Windows file lock")

    with patch.object(Path, "write_text", return_value=1), patch(
        "functions.decision_council.runtime_checkpoint.os.replace",
        side_effect=replace_with_transient_lock,
    ), patch("functions.decision_council.runtime_checkpoint.time.sleep"):
        target = write_run_checkpoint(
            ".",
            status="complete",
            current_day=20,
            total_days=20,
            stage="complete",
        )
    assert target.name == "run_checkpoint.json"
    assert len(calls) == 3
    print("[PASS] transient checkpoint replacement lock is retried and recovered")


if __name__ == "__main__":
    main()
