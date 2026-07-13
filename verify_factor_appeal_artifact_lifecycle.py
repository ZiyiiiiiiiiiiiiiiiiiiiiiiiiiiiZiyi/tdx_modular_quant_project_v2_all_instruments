from __future__ import annotations

import json
from pathlib import Path
import tempfile

from functions.factor_selection import factor_cabinet_builder as builder


def _write_run(path: Path, *, run_kind: str, status: str, admitted: bool = True) -> None:
    path.mkdir(parents=True)
    (path / "appeal_summary.csv").write_text("factor_name,new_decision\nx,promote_candidate\n", encoding="utf-8")
    if admitted:
        (path / "admitted_v2.csv").write_text("factor_name,new_decision\nx,promote_candidate\n", encoding="utf-8")
    (path / "artifact_manifest.json").write_text(
        json.dumps({"status": status, "run_kind": run_kind}), encoding="utf-8"
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="appeal_lifecycle_") as tmp:
        root = Path(tmp)
        production = root / "run_production"
        test_run = root / "run_test"
        incomplete = root / "run_incomplete"
        _write_run(production, run_kind="production", status="complete")
        _write_run(test_run, run_kind="test", status="complete")
        _write_run(incomplete, run_kind="production", status="running", admitted=False)

        assert builder._is_consumable_appeal_run(production, allow_legacy=False)
        assert not builder._is_consumable_appeal_run(test_run, allow_legacy=False)
        assert not builder._is_consumable_appeal_run(incomplete, allow_legacy=False)
        try:
            builder._resolve_appeal_run_dir(test_run)
        except ValueError:
            pass
        else:
            raise AssertionError("explicit test appeal run must be rejected")
    print("[PASS] appeal artifact lifecycle rejects test and incomplete runs")


if __name__ == "__main__":
    main()
