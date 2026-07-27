from __future__ import annotations

import ast
from pathlib import Path


def main() -> None:
    module = ast.parse(Path("run_governance_experiments.py").read_text(encoding="utf-8"))
    target = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_single_experiment"
    )
    source = ast.unparse(target)
    assert "control_mode in {" in source
    assert "'aggressive_profit'" in source and "'aggressive_lean'" in source
    assert "GOVERNANCE_OUTPUT_DIR / 'scap'" in source
    assert "f'{exit_stage.lower()}_l{loss_basis_points}'" in source
    print("[PASS] governance experiment SCAP modes use the legacy-Windows-safe short root")


if __name__ == "__main__":
    main()
