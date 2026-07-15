"""Verify governance Web/CLI entrypoints match the shared experiment contract."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def _function_keywords(tree: ast.Module, function_name: str) -> set[str]:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            positional = [argument.arg for argument in node.args.args]
            keyword_only = [argument.arg for argument in node.args.kwonlyargs]
            return set(positional + keyword_only)
    raise AssertionError(f"function not found: {function_name}")


def _calls(tree: ast.Module, function_name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == function_name
    ]


def main() -> int:
    experiment_path = ROOT / "run_governance_experiments.py"
    main_path = ROOT / "main.py"
    experiment_tree = ast.parse(experiment_path.read_text(encoding="utf-8"), filename=str(experiment_path))
    main_tree = ast.parse(main_path.read_text(encoding="utf-8"), filename=str(main_path))
    accepted = _function_keywords(experiment_tree, "run_single_experiment")
    calls = _calls(main_tree, "run_single_experiment") + _calls(experiment_tree, "run_single_experiment")
    assert calls, "no governance experiment calls found"
    for call in calls:
        supplied = {keyword.arg for keyword in call.keywords if keyword.arg is not None}
        unexpected = sorted(supplied - accepted)
        assert not unexpected, f"run_single_experiment call at line {call.lineno} has unexpected keywords: {unexpected}"

    main_source = main_path.read_text(encoding="utf-8")
    required_routes = {
        "layer validation": "def run_governance_layer_validation_from_main",
        "enhanced diagnostics": "def run_governance_layer_ablation_suite_from_main",
        "mainline review": "def run_governance_mainline_review_from_main",
        "registered comparison": "def run_registered_mainline_v2_suite_from_main",
    }
    for label, marker in required_routes.items():
        assert marker in main_source, f"missing governance route: {label}"
    for field in ("factor_source", "factor_cabinet_run_id", "factor_cabinet_path"):
        assert main_source.count(f"{field}={field}") >= 3, f"governance routes do not consistently pass {field}"

    print(f"[PASS] {len(calls)} run_single_experiment calls match the shared keyword contract")
    print("[PASS] layer, enhanced, mainline, and registered routes are present")
    print("[PASS] cabinet source, run_id, and path are forwarded across governance routes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
