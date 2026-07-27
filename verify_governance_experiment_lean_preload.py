from __future__ import annotations

import ast
from pathlib import Path

import pandas as pd

from functions.decision_council.runner import governance_preload_calendar_days


def main() -> None:
    assert governance_preload_calendar_days("normal", configured_days=60) == 60
    assert governance_preload_calendar_days("aggressive_lean", configured_days=60) == 420
    assert governance_preload_calendar_days("lean", configured_days=500) == 500

    module = ast.parse(Path("run_governance_experiments.py").read_text(encoding="utf-8"))
    loader = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "_load_governance_features"
    )
    source = ast.unparse(loader)
    assert "governance_preload_calendar_days(governance_control_mode)" in source
    assert "start_date - pd.Timedelta(days=preload_calendar_days)" in source
    assert "start_date - pd.Timedelta(days=60)" not in source
    assert "start_date=load_start" in source

    trade_start = pd.Timestamp("2025-01-01")
    load_start = trade_start - pd.Timedelta(
        days=governance_preload_calendar_days("aggressive_lean", configured_days=60)
    )
    assert load_start == pd.Timestamp("2023-11-08")
    print("[PASS] experiment and runner share the SCAP-V3 Lean preload contract")


if __name__ == "__main__":
    main()
