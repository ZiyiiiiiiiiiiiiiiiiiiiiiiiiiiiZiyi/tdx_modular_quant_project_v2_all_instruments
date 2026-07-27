from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from functions.data.pit_level1_pipeline import should_preserve_historical_membership


def main() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "index_membership_pit.parquet"
        pd.DataFrame({"index_code": ["000300"]}).to_parquet(path, index=False)
        manifest = path.with_suffix(".manifest.json")
        manifest.write_text(json.dumps({"provenance": {"source": "current_snapshot"}}), encoding="utf-8")
        assert not should_preserve_historical_membership(path)
        manifest.write_text(
            json.dumps({"provenance": {"source": "baostock_plus_a500_historical_reconstruction"}}),
            encoding="utf-8",
        )
        assert should_preserve_historical_membership(path)
    print("[PASS] local Level-1 build preserves an existing historical membership table")


if __name__ == "__main__":
    main()
