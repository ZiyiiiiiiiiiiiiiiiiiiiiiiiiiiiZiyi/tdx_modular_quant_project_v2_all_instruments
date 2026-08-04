"""Regression: detached-console logging cannot abort governance persistence."""
from __future__ import annotations

import os
from pathlib import Path
from tempfile import mkdtemp
from unittest.mock import patch

from functions.decision_council.quality_reports import _log_quality_stage
from functions.decision_council.runner import GovernanceBacktestRunner


class _RunnerStub:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir


def main() -> int:
    with patch("builtins.print", side_effect=OSError(22, "Invalid argument")):
        _log_quality_stage("detached_console")

    output_dir = Path(mkdtemp(prefix="governance_save_log_"))
    try:
        stub = _RunnerStub(output_dir)
        with patch("builtins.print", side_effect=OSError(22, "Invalid argument")):
            GovernanceBacktestRunner._log_save_stage(stub, "write_extra_csv", frames=3)
        manifest = output_dir / "artifact_manifest.json"
        if not manifest.is_file():
            print("[FAIL] manifest was not written after console failure")
            return 1
    finally:
        manifest = output_dir / "artifact_manifest.json"
        if manifest.is_file():
            manifest.unlink()
        os.rmdir(output_dir)

    print("[PASS] detached-console logging is fail-open; manifest remains authoritative")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
