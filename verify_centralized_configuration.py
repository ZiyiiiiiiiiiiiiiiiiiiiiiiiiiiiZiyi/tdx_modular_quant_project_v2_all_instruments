# -*- coding: utf-8 -*-
"""Verify configuration validity and prevent new scattered CLI defaults."""
from __future__ import annotations

import ast
import os
from pathlib import Path

import config


ROOT = Path(__file__).resolve().parent


def main():
    failures = []
    _verify_configuration_api(failures)
    _verify_argparse_defaults(failures)
    _verify_no_duplicated_core_parameters(failures)
    _verify_position_management_columns(failures)
    if failures:
        raise AssertionError("\n".join(failures))
    print("[PASS] centralized configuration contract")


def _verify_configuration_api(failures):
    errors = config.validate_configuration()
    if errors:
        failures.extend(f"configuration validation: {item}" for item in errors)
    snapshot = config.parameter_snapshot()
    required = {
        "STRATEGY_START_DATE",
        "STRATEGY_END_DATE",
        "STRATEGY_TOP_N",
        "POSITION_KELLY_SCALE",
        "AUTO_COMPLETE_FETCH_BATCH_SIZE",
        "ARTIFACT_VALIDATION_SYMBOL_SAMPLE_SIZE",
    }
    missing = required - set(snapshot)
    if missing:
        failures.append(f"configuration snapshot missing keys: {sorted(missing)}")
    if config.get_parameter("strategy_start_date") != config.STRATEGY_START_DATE:
        failures.append("case-insensitive get_parameter lookup failed")


def _verify_argparse_defaults(failures):
    for path in ROOT.glob("*.py"):
        if path.name in {Path(__file__).name, "config_interface.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_add_argument_call(node):
                continue
            for keyword in node.keywords:
                if keyword.arg != "default":
                    continue
                value = keyword.value
                if isinstance(value, ast.Constant) and value.value is not None:
                    failures.append(
                        f"{path.name}:{node.lineno} has literal argparse default {value.value!r}; "
                        "move it to config.py"
                    )
                elif isinstance(value, (ast.List, ast.Tuple, ast.Dict)):
                    failures.append(
                        f"{path.name}:{node.lineno} has container argparse default; move it to config.py"
                    )


def _is_add_argument_call(node):
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_argument"
    )


def _verify_no_duplicated_core_parameters(failures):
    protected = {
        "STRATEGY_START_DATE",
        "STRATEGY_END_DATE",
        "STRATEGY_TOP_N",
        "STRATEGY_FREQ",
        "STRATEGY_INCLUDE_TYPES",
        "STRATEGY_SCORE_COL",
        "POSITION_KELLY_SCALE",
        "COMMISSION_RATE",
        "STAMP_DUTY_RATE",
        "SLIPPAGE_RATE",
        "AUTO_COMPLETE_MAX_STRATEGY_WORKERS",
    }
    excluded_trees = {"data", "results", "runs", "reports", ".git", "__pycache__"}
    python_files = []
    for directory, dirnames, filenames in os.walk(ROOT, topdown=True):
        dirnames[:] = [name for name in dirnames if name not in excluded_trees]
        python_files.extend(
            Path(directory) / name for name in filenames if name.endswith(".py")
        )
    for path in python_files:
        if path.name == "config.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id in protected:
                    failures.append(
                        f"{path.relative_to(ROOT)}:{node.lineno} duplicates centralized parameter {target.id}"
                    )


def _verify_position_management_columns(failures):
    from functions.feature_engineering import required_feature_columns_for_strategy

    required = set(required_feature_columns_for_strategy("position_managed_kelly"))
    missing = {"open", "high", "low", "close", "volume"} - required
    if missing:
        failures.append(f"position_managed_kelly misses required OHLCV columns: {sorted(missing)}")


if __name__ == "__main__":
    main()
