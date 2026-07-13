from __future__ import annotations

import json
from pathlib import Path
import tempfile

import pandas as pd

from functions.decision_council.factor_appeal_judge import merge_appeal_artifacts


def _artifact(root: Path, name: str, rows: list[dict]) -> Path:
    output = root / name
    output.mkdir()
    (output / "artifact_manifest.json").write_text(
        json.dumps({"run_id": name, "run_kind": "production", "status": "complete"}),
        encoding="utf-8",
    )
    frame = pd.DataFrame(rows)
    frame.to_csv(output / "appeal_summary.csv", index=False)
    frame.to_csv(output / "admitted_v2.csv", index=False)
    pd.DataFrame(columns=frame.columns).to_csv(output / "watchlist_v2.csv", index=False)
    return output


def main() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        first = _artifact(root, "first", [{"factor_name": "rsi_recovery", "ic_ir": 0.1}])
        second = _artifact(
            root,
            "second",
            [
                {"factor_name": "orderflow_efficiency_w20_s3", "ic_ir": 0.2},
                {"factor_name": "rsi_recovery", "ic_ir": 0.05},
            ],
        )
        saved = merge_appeal_artifacts([first, second], output_root=root / "merged")
        admitted = pd.read_csv(saved["admitted_v2"])
        manifest = json.loads(saved["artifact_manifest"].read_text(encoding="utf-8"))
        assert admitted["factor_name"].tolist() == ["orderflow_efficiency_w20_s3", "rsi_recovery"]
        assert manifest["status"] == "complete"
        assert manifest["admitted_count"] == 2
    print("[PASS] appeal artifacts merge with provenance and factor-name deduplication")


if __name__ == "__main__":
    main()
