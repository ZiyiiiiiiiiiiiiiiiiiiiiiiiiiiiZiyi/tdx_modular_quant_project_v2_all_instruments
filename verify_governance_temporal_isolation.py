"""Product verification for fail-closed factor research windows."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile

from functions.research.temporal_contract import (
    assert_artifact_temporal_isolation,
    audit_artifact_lineage,
    validate_temporal_order,
)


def main() -> None:
    clean = validate_temporal_order(
        factor_discovery_end="2023-12-29",
        role_calibration_end="2024-01-29",
        oos_start="2024-02-01",
    )
    assert clean["temporal_isolation_pass"]
    print("[PASS] clean discovery/calibration/OOS order is accepted")

    overlap = validate_temporal_order(
        factor_discovery_end="2024-02-01",
        role_calibration_end="2024-01-29",
        oos_start="2024-02-01",
    )
    assert not overlap["temporal_isolation_pass"]
    print("[PASS] overlapping explicit research windows fail closed")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        upstream = root / "upstream"
        upstream.mkdir()
        (upstream / "fast_factor_judge_manifest.csv").write_text(
            "analysis_start_date,analysis_end_date\n2021-01-01,2024-12-31\n",
            encoding="utf-8",
        )
        cabinet = root / "factor_cabinet.json"
        cabinet.write_text(json.dumps({"v1_run_dir": str(upstream)}), encoding="utf-8")
        evidence, summary = audit_artifact_lineage(cabinet, oos_start="2024-02-01")
        assert not summary["temporal_isolation_pass"]
        assert summary["latest_upstream_analysis_end"] == "2024-12-31"
        assert not evidence.empty
        try:
            assert_artifact_temporal_isolation(cabinet, oos_start="2024-02-01")
        except ValueError as exc:
            assert "overlaps_oos" in str(exc)
        else:
            raise AssertionError("overlapping lineage should raise")
    print("[PASS] recursive upstream overlap is detected and blocked")

    current = Path(
        "results/factor_cabinet/pruned_run20260714_184846_581132_20260715_230524/factor_cabinet.json"
    )
    if current.exists():
        _, summary = audit_artifact_lineage(
            current,
            oos_start="2024-02-01",
            extra_manifest_paths=[
                "results/decision_council/fast_factor_judge/hs300_csi500_a500_strict/"
                "run20260705_180001_095951/fast_factor_judge_manifest.csv"
            ],
        )
        assert not summary["temporal_isolation_pass"]
        assert summary["latest_upstream_analysis_end"] == "2024-12-31"
        print("[PASS] selected 74-factor cabinet is correctly classified as OOS-overlapping")


if __name__ == "__main__":
    main()
