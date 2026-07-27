from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pandas as pd

import functions.decision_council.factor_cabinet_feature_cache as cache_module


def _write_artifact(root: Path, run_id: str, start: str, end: str, created: str) -> None:
    cache_dir = root / run_id
    cache_dir.mkdir(parents=True, exist_ok=True)
    stem = f"factor_cabinet_features_{start.replace('-', '')}_{end.replace('-', '')}"
    parquet_path = cache_dir / f"{stem}.parquet"
    manifest_path = cache_dir / f"{stem}.manifest.json"
    dates = pd.date_range(start, end, freq="D")
    pd.DataFrame(
        {
            "date": dates,
            "symbol": ["sh600000"] * len(dates),
            "cand_test": range(len(dates)),
        }
    ).to_parquet(parquet_path, index=False)
    manifest_path.write_text(
        json.dumps(
            {
                "artifact_type": "factor_cabinet_feature_cache",
                "factor_cabinet_run_id": run_id,
                "cabinet_manifest_hash": "cabinet-hash",
                "raw_columns": ["cand_test"],
                "requested_date_min": start,
                "requested_date_max": end,
                "feature_input": {"exists": True, "size": 1, "mtime_ns": 2},
                "parquet_path": str(parquet_path),
                "created_at": created,
            }
        ),
        encoding="utf-8",
    )


def main() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        run_id = "stitch-test"
        _write_artifact(root, run_id, "2023-11-01", "2024-12-31", "2026-01-01")
        _write_artifact(root, run_id, "2025-01-01", "2025-09-30", "2026-01-02")
        spec = SimpleNamespace(
            uses_factor_cabinet=True,
            factor_cabinet_run_id=run_id,
            cabinet_manifest_hash="cabinet-hash",
            model_feature_map={"test": "cand_test"},
        )
        original_fingerprint = cache_module.file_fingerprint
        cache_module.file_fingerprint = lambda _path: {
            "exists": True,
            "size": 1,
            "mtime_ns": 2,
        }
        try:
            found = cache_module._find_factor_cabinet_feature_cache_cover(
                spec,
                "2023-11-08",
                "2025-09-25",
                feature_path=Path("unused.parquet"),
                root=root,
            )
        finally:
            cache_module.file_fingerprint = original_fingerprint
        assert len(found) == 2
        assert found[0][1]["requested_date_max"] == "2024-12-31"
        assert found[1][1]["requested_date_min"] == "2025-01-01"
    print("[PASS] adjacent identity-consistent factor cabinet caches cover the Lean window")


if __name__ == "__main__":
    main()
