"""Verify factor_cabinet pruning invariants and runtime compatibility."""
from __future__ import annotations

import json
from pathlib import Path

from functions.decision_council.factor_cabinet_pruner import build_factor_cabinet_pruned
from functions.decision_council.factor_source import (
    FACTOR_SOURCE_LATEST_CABINET,
    FACTOR_SOURCE_SELECTED_CABINET,
    resolve_factor_source,
)


SOURCE_RUN_ID = "run20260706_183553_702097"


def _pass(message: str) -> None:
    print(f"[PASS] {message}")


def _fail(message: str) -> None:
    raise AssertionError(f"[FAIL] {message}")


def main() -> int:
    source_spec = resolve_factor_source(
        factor_source=FACTOR_SOURCE_SELECTED_CABINET,
        factor_cabinet_run_id=SOURCE_RUN_ID,
    )
    source_path = Path(source_spec.factor_cabinet_path)
    source_payload_before = json.loads(source_path.read_text(encoding="utf-8"))
    source_names = {str(item.get("factor_name")) for item in source_payload_before.get("factors", [])}
    source_count = len(source_names)
    if source_count <= 0:
        _fail("source cabinet has no factors")

    saved = build_factor_cabinet_pruned(
        factor_source=FACTOR_SOURCE_SELECTED_CABINET,
        factor_cabinet_run_id=source_spec.factor_cabinet_run_id,
        output_root=Path("reports") / "verify_factor_cabinet_pruner" / "factor_cabinet",
        report_root=Path("reports") / "verify_factor_cabinet_pruner" / "reports",
    )
    pruned_path = Path(saved["factor_cabinet"])
    if not pruned_path.exists():
        _fail("pruned factor_cabinet.json was not written")
    payload = json.loads(pruned_path.read_text(encoding="utf-8"))
    factors = payload.get("factors", [])
    pruned_names = {str(item.get("factor_name")) for item in factors}
    if not pruned_names:
        _fail("pruned cabinet is empty")
    if not pruned_names <= source_names:
        _fail("pruned cabinet introduced factors not present in source cabinet")
    if len(pruned_names) >= source_count:
        _fail("pruned cabinet did not reduce factor count")
    _pass(f"pruned cabinet keeps only existing factors ({len(pruned_names)}/{source_count})")

    source_payload_after = json.loads(source_path.read_text(encoding="utf-8"))
    if source_payload_after != source_payload_before:
        _fail("source factor_cabinet.json changed during prune")
    _pass("source factor cabinet is not modified")

    selected = resolve_factor_source(
        factor_source=FACTOR_SOURCE_SELECTED_CABINET,
        factor_cabinet_run_id=str(payload.get("run_id")),
        factor_cabinet_path=pruned_path,
    )
    if selected.factor_cabinet_run_id != str(payload.get("run_id")):
        _fail("selected_factor_cabinet did not resolve pruned run_id")
    if selected.factor_count != len(factors):
        _fail("selected_factor_cabinet factor count does not match pruned cabinet")
    if selected.factor_source != FACTOR_SOURCE_SELECTED_CABINET:
        _fail("selected_factor_cabinet did not preserve selected source")
    _pass("selected_factor_cabinet resolves pruned cabinet")

    summary_path = Path(saved["prune_summary"])
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    invariants = summary.get("invariants", {})
    if not invariants.get("no_new_factors"):
        _fail("prune summary no_new_factors invariant failed")
    if not invariants.get("strict_entry_alpha_preserved"):
        _fail("strict entry alpha was not preserved")
    _pass("prune summary invariants pass")

    try:
        resolve_factor_source(factor_source="legacy_bundle", alpha_bundle="validation_core_bundle")
    except ValueError:
        _pass("legacy resolver still rejects validation_core_bundle fallback")
    else:
        _fail("legacy resolver allowed validation_core_bundle")

    print(f"[PASS] pruned_run_id={payload.get('run_id')}")
    print(f"[PASS] pruned_path={pruned_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
