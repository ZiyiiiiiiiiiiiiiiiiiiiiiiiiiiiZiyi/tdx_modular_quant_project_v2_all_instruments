from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from functions.investable_universe import validate_pit_membership_manifest_coverage


def main() -> None:
    with TemporaryDirectory() as directory:
        pit_path = Path(directory) / "index_membership_pit.parquet"
        pd.DataFrame({"index_code": ["000300"]}).to_parquet(pit_path, index=False)
        manifest = {
            "provenance": {"coverage_start": "2025-01-02", "coverage_end": "2025-01-08"}
        }
        pit_path.with_suffix(".manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        inside = validate_pit_membership_manifest_coverage(
            start_date="2025-01-02", end_date="2025-01-08", pit_path=pit_path
        )
        assert inside["status"] == "pass", inside
        after = validate_pit_membership_manifest_coverage(
            start_date="2025-01-02", end_date="2025-01-09", pit_path=pit_path
        )
        assert after["status"] == "blocked", after
        assert after["reason"] == "pit_membership_coverage_outside_requested_window", after
        before = validate_pit_membership_manifest_coverage(
            start_date="2025-01-01", end_date="2025-01-08", pit_path=pit_path
        )
        assert before["status"] == "blocked", before
    print("[PASS] PIT membership manifest coverage is enforced")


if __name__ == "__main__":
    main()
