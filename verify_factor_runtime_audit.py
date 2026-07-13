import json
from pathlib import Path

from functions.decision_council.factor_runtime_audit import (
    build_factor_runtime_audit,
    save_factor_runtime_audit,
)
from functions.decision_council.factor_source import (
    FACTOR_SOURCE_LATEST_CABINET,
    FACTOR_SOURCE_LEGACY,
    FACTOR_SOURCE_SELECTED_CABINET,
    LEGACY_GOVERNANCE_ALPHA_BUNDLE,
    list_factor_cabinet_runs,
    resolve_factor_source,
)


def _pass(message: str) -> None:
    print(f"[PASS] {message}")


def _latest_run_id() -> str:
    runs = list_factor_cabinet_runs()
    assert runs, "No factor_cabinet runs found under results/factor_cabinet"
    return str(runs[0]["run_id"])


def check_latest_factor_cabinet_loads_cabinet() -> None:
    spec = resolve_factor_source(factor_source=FACTOR_SOURCE_LATEST_CABINET)
    audit = build_factor_runtime_audit(spec, requested_factor_source=FACTOR_SOURCE_LATEST_CABINET)
    assert audit.factor_source == FACTOR_SOURCE_LATEST_CABINET
    assert not audit.legacy_used
    assert not audit.fallback_detected
    assert audit.factor_cabinet_run_id
    assert Path(audit.factor_cabinet_path).exists()
    assert audit.loaded_factor_count > 0
    assert len(audit.loaded_factor_names) == audit.loaded_factor_count
    assert sum(audit.loaded_role_distribution.values()) == audit.loaded_factor_count
    _pass("latest_factor_cabinet loads factor_cabinet.json with runtime audit evidence")


def check_selected_factor_cabinet_loads_requested_run_id() -> str:
    run_id = _latest_run_id()
    spec = resolve_factor_source(
        factor_source=FACTOR_SOURCE_SELECTED_CABINET,
        factor_cabinet_run_id=run_id,
    )
    audit = build_factor_runtime_audit(spec, requested_factor_source=FACTOR_SOURCE_SELECTED_CABINET)
    assert audit.factor_source == FACTOR_SOURCE_SELECTED_CABINET
    assert audit.factor_cabinet_run_id == run_id
    assert not audit.legacy_used
    assert audit.loaded_factor_count > 0
    _pass("selected_factor_cabinet loads the requested run_id")
    return run_id


def check_legacy_bundle_is_explicit() -> None:
    spec = resolve_factor_source(
        factor_source=FACTOR_SOURCE_LEGACY,
        alpha_bundle=LEGACY_GOVERNANCE_ALPHA_BUNDLE,
    )
    audit = build_factor_runtime_audit(spec, requested_factor_source=FACTOR_SOURCE_LEGACY)
    assert audit.factor_source == FACTOR_SOURCE_LEGACY
    assert audit.legacy_used
    assert audit.factor_cabinet_path == ""
    assert audit.loaded_factor_count == 0
    assert not audit.fallback_detected
    _pass("legacy_bundle is explicitly marked as legacy_used")


def check_cabinet_mode_blocks_fallback() -> None:
    missing_root = Path("reports") / "verify_factor_runtime_audit" / "missing_factor_cabinet_root"
    try:
        resolve_factor_source(factor_source=FACTOR_SOURCE_LATEST_CABINET, root=missing_root)
    except FileNotFoundError as exc:
        assert "No factor_cabinet.json found" in str(exc)
        _pass("cabinet mode raises when cabinet is unavailable instead of falling back")
        return
    raise AssertionError("latest_factor_cabinet unexpectedly resolved from a missing root")


def check_report_contains_audit_file(run_id: str) -> None:
    spec = resolve_factor_source(
        factor_source=FACTOR_SOURCE_SELECTED_CABINET,
        factor_cabinet_run_id=run_id,
    )
    audit = build_factor_runtime_audit(spec, requested_factor_source=FACTOR_SOURCE_SELECTED_CABINET)
    output_dir = Path("reports") / "verify_factor_runtime_audit"
    path = save_factor_runtime_audit(audit, output_dir)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "factor_runtime_audit.json"
    assert payload["factor_source"] == FACTOR_SOURCE_SELECTED_CABINET
    assert payload["factor_cabinet_run_id"] == run_id
    assert payload["factor_count"] == payload["loaded_factor_count"]
    assert payload["legacy_used"] is False
    assert payload["fallback_detected"] is False
    _pass("factor_runtime_audit.json is written with required report fields")


def main() -> int:
    check_latest_factor_cabinet_loads_cabinet()
    run_id = check_selected_factor_cabinet_loads_requested_run_id()
    check_legacy_bundle_is_explicit()
    check_cabinet_mode_blocks_fallback()
    check_report_contains_audit_file(run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
