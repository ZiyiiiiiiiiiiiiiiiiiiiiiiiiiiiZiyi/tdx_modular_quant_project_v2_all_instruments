"""Verify enhanced layer-ablation factor-source routing without a backtest."""
from __future__ import annotations

import ast
from pathlib import Path

import main


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main_test() -> int:
    selected, skipped = main._layer_ablation_suite_for_factor_source("latest_factor_cabinet")
    selected_ids = {row[2] for row in selected}
    check(selected_ids == main._CABINET_COMPATIBLE_LAYER_ABLATION_STEPS, "cabinet suite keeps only real control-layer variants")
    check(len(skipped) == 8, "legacy bundle-only module rows are explicitly skipped")
    try:
        main._layer_ablation_suite_for_factor_source("legacy_bundle")
    except ValueError as exc:
        check("diversified_pre_screen_bundle_v2" in str(exc), "legacy diagnostic bundle masquerading is rejected")
    else:
        raise AssertionError("legacy enhanced suite should fail")

    source = Path("main.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    target = next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "run_governance_layer_ablation_suite_from_main"
    )
    calls = [
        node for node in ast.walk(target)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "run_single_experiment"
    ]
    check(len(calls) == 1, "suite has one governed experiment call site")
    keywords = {item.arg for item in calls[0].keywords}
    required = {"factor_source", "factor_cabinet_run_id", "factor_cabinet_path"}
    check(required <= keywords, "factor-source contract is forwarded at the call site")
    all_experiment_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "run_single_experiment"
    ]
    missing_contract = [
        node.lineno for node in all_experiment_calls
        if not required <= {item.arg for item in node.keywords}
    ]
    check(not missing_contract, f"all main.py governance experiment calls forward factor-source contract: {missing_contract}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_test())
