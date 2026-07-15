from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from functions.factor_selection.factor_cabinet_builder import (
    find_latest_pruned_cabinet,
    find_latest_pruned_descendant,
)


def _write(root: Path, run_id: str, **metadata) -> Path:
    output = root / run_id
    output.mkdir(parents=True)
    path = output / "factor_cabinet.json"
    payload = {"run_id": run_id, "factors": [{"factor_name": "factor_a"}], **metadata}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def main() -> int:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        base_path = _write(root, "base", artifact_type="factor_cabinet_pit_augmented")
        assert find_latest_pruned_descendant(base_path, search_root=root) is None

        pruned_path = _write(
            root,
            "pruned_base_1",
            artifact_type="factor_cabinet_pruned",
            source_run_id="base",
        )
        result = find_latest_pruned_descendant(base_path, search_root=root)
        assert result is not None
        assert result[0] == "pruned_base_1"
        assert result[1] == pruned_path.resolve()
        latest_pruned = find_latest_pruned_cabinet(search_root=root)
        assert latest_pruned is not None
        assert latest_pruned[0] == "pruned_base_1"

        assert find_latest_pruned_descendant(pruned_path, search_root=root) is None

        unrelated_path = _write(root, "unrelated", artifact_type="factor_cabinet")
        assert find_latest_pruned_descendant(unrelated_path, search_root=root) is None

    print("[PASS] factor cabinet builder detects pruned descendants without crossing lineages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
