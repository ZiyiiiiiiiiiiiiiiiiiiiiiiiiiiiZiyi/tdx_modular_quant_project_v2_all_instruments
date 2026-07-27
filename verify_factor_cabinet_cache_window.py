from __future__ import annotations

import ast
from pathlib import Path


def main() -> None:
    module = ast.parse(Path("main.py").read_text(encoding="utf-8"))
    target = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_factor_cabinet_feature_cache_from_main"
    )
    source = ast.unparse(target)
    assert "governance_max_days" in source
    assert "bounded_observed_feature_end" in source
    assert source.index("end_date = bounded_observed_feature_end") < source.index(") = build_factor_cabinet_feature_cache")
    print("[PASS] factor cabinet cache respects the bounded observed governance window")


if __name__ == "__main__":
    main()
