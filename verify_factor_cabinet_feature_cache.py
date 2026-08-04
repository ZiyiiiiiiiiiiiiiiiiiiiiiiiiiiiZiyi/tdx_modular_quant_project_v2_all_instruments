"""Verify factor_cabinet feature cache routing without running a full backtest."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from functions.decision_council.factor_cabinet_feature_cache import (
    FACTOR_CABINET_FEATURE_CACHE_ROOT,
    build_factor_cabinet_feature_cache,
    attach_factor_cabinet_feature_cache,
    load_factor_cabinet_feature_cache,
    validate_factor_cabinet_feature_cache_artifacts,
)
from functions.decision_council.factor_source import (
    FACTOR_SOURCE_LATEST_CABINET,
    FactorSourceSpec,
    resolve_factor_source,
)


ROOT = Path(__file__).resolve().parent


def _pass(name: str) -> None:
    print(f"[PASS] {name}")


def _fail(name: str, detail: str) -> None:
    print(f"[FAIL] {name}: {detail}")
    raise AssertionError(name)


def _assert_contains(path: Path, name: str, needles: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    missing = [needle for needle in needles if needle not in text]
    if missing:
        _fail(name, f"missing text: {missing}")
    _pass(name)


def check_latest_cabinet_resolves() -> None:
    spec = resolve_factor_source(factor_source=FACTOR_SOURCE_LATEST_CABINET)
    if not spec.uses_factor_cabinet:
        _fail("latest_factor_cabinet resolves cabinet", "spec.uses_factor_cabinet is false")
    if not spec.factor_cabinet_run_id or spec.factor_count <= 0:
        _fail("latest_factor_cabinet resolves cabinet", f"bad spec: {spec}")
    _pass(
        "latest_factor_cabinet resolves cabinet "
        f"run_id={spec.factor_cabinet_run_id}, factors={spec.factor_count}"
    )


def check_cache_builder_is_materialized_path() -> None:
    source = inspect.getsource(build_factor_cabinet_feature_cache)
    module_source = (ROOT / "functions" / "decision_council" / "factor_cabinet_feature_cache.py").read_text(encoding="utf-8")
    required = [
        "_factor_cabinet_raw_columns(spec)",
        "GOVERNANCE_PRE_SCREEN_FACTOR_CACHE_LOOKBACK_DAYS",
        "artifact_type",
        "factor_cabinet_feature_cache",
        "requested_date_min",
    ]
    missing = [item for item in required if item not in source]
    if missing:
        _fail("cache builder materializes cabinet features", f"missing {missing}")
    chunk_required = [
        "_build_factor_cabinet_feature_cache_chunked",
        "_iter_fixed_day_chunks",
        "partitioned_parquet_directory",
        "pq.write_table",
        "dataset_path",
        "storage_layout",
        "chunk_compute",
        "chunk_write",
        "fixed_45_calendar_days",
    ]
    chunk_missing = [item for item in chunk_required if item not in module_source]
    if chunk_missing:
        _fail("cache builder materializes cabinet features", f"missing chunked implementation {chunk_missing}")
    _pass("cache builder materializes cabinet features with lookback")


def check_missing_cache_fails_closed() -> None:
    fake_spec = FactorSourceSpec(
        factor_source=FACTOR_SOURCE_LATEST_CABINET,
        alpha_bundle="factor_cabinet:verify_missing_cache",
        factor_cabinet_run_id="verify_missing_cache_do_not_create",
        factor_cabinet_path="verify_missing_cache/factor_cabinet.json",
        factor_count=1,
        model_feature_map={"verify_factor": "cand_verify_factor"},
        role_map={"verify_factor": "entry_alpha"},
    )
    try:
        load_factor_cabinet_feature_cache(fake_spec, "2021-01-04", "2021-01-08")
    except FileNotFoundError as exc:
        message = str(exc)
        if "--factor-cabinet-feature-cache" not in message:
            _fail("missing cabinet cache fails closed", message)
        _pass("missing cabinet cache fails closed")
        return
    _fail("missing cabinet cache fails closed", "load unexpectedly succeeded")


def check_runtime_uses_cache_for_cabinet() -> None:
    _assert_contains(
        ROOT / "run_governance_experiments.py",
        "layer validation cabinet path reads factor_cabinet cache",
        [
            "attach_factor_cabinet_feature_cache",
            "factor_spec is not None and factor_spec.uses_factor_cabinet",
            "start_date=start_date",
        ],
    )
    _assert_contains(
        ROOT / "functions" / "decision_council" / "runner.py",
        "direct governance cabinet path reads factor_cabinet cache",
        [
            "attach_factor_cabinet_feature_cache",
            "if factor_spec.uses_factor_cabinet:",
            "cabinet_cache_start = (",
            '== "aggressive_lean"',
            "cache_start",
            "effective_start",
        ],
    )


def check_web_and_cli_entrypoints() -> None:
    _assert_contains(
        ROOT / "main.py",
        "CLI and interactive entrypoint expose factor_cabinet cache",
        [
            "--factor-cabinet-feature-cache",
            "run_factor_cabinet_feature_cache_from_main",
            '"factor_cabinet_feature_cache"',
        ],
    )
    _assert_contains(
        ROOT / "main_launcher_web.py",
        "Web entrypoint exposes factor_cabinet cache",
        [
            'id="factor_cabinet_feature_cache"',
            '"factor_cabinet_feature_cache"',
            "latest_factor_cabinet",
            "requiresUniverse",
        ],
    )


def check_interactive_order_prepares_cache_first() -> None:
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    cache_index = text.find('if "factor_cabinet_feature_cache" in tasks:')
    layer_index = text.find('if "governance_layer_validation" in tasks:')
    if cache_index < 0 or layer_index < 0:
        _fail("interactive order prepares cache before governance", "required task blocks not found")
    if cache_index > layer_index:
        _fail("interactive order prepares cache before governance", "cache task runs after layer validation")
    _pass("interactive order prepares cache before governance")


def check_partitioned_cache_artifact_contract() -> None:
    manifests = sorted(
        FACTOR_CABINET_FEATURE_CACHE_ROOT.glob("run*/factor_cabinet_features_*.manifest.json"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    partitioned = []
    for manifest_path in manifests:
        import json

        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if payload.get("storage_layout") == "partitioned_parquet_directory":
            partitioned.append((manifest_path, payload))
    if not partitioned:
        _fail("partitioned cache artifact contract", "no partitioned cache manifest is available")
    manifest_path, payload = partitioned[0]
    parquet_path, checked_manifest = validate_factor_cabinet_feature_cache_artifacts(
        payload.get("parquet_path", ""),
        manifest_path,
    )
    if not parquet_path.is_dir() or checked_manifest != manifest_path.resolve():
        _fail("partitioned cache artifact contract", f"unexpected artifacts: {parquet_path}, {checked_manifest}")
    _pass("partitioned cache directory and manifest validate as one artifact")


def check_preloaded_passthrough_columns_do_not_collide() -> None:
    spec = FactorSourceSpec(
        factor_source=FACTOR_SOURCE_LATEST_CABINET,
        alpha_bundle="factor_cabinet:collision_smoke",
        factor_cabinet_run_id="collision_smoke",
        factor_cabinet_path="collision_smoke/factor_cabinet.json",
        factor_count=2,
        model_feature_map={
            "passthrough": "score_existing",
            "generated": "cand_missing",
        },
        role_map={"passthrough": "entry_alpha", "generated": "timing_filter"},
    )
    base = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-02", "2024-01-02"]),
        "symbol": ["000001.SZ", "600000.SH"],
        "score_existing": [1.0, 2.0],
    })
    cached_missing = pd.DataFrame({
        "date": base["date"],
        "symbol": base["symbol"],
        "cand_missing": [3.0, 4.0],
    })
    with patch(
        "functions.decision_council.factor_cabinet_feature_cache.load_factor_cabinet_feature_cache",
        return_value=cached_missing,
    ) as loader:
        merged = attach_factor_cabinet_feature_cache(
            base,
            spec=spec,
            start_date="2024-01-02",
            end_date="2024-01-02",
        )
    requested = loader.call_args.kwargs.get("requested_columns")
    if requested != ("cand_missing",):
        _fail("preloaded passthrough cache merge", f"unexpected requested columns: {requested}")
    if list(merged["score_existing"]) != [1.0, 2.0] or "cand_missing" not in merged.columns:
        _fail("preloaded passthrough cache merge", f"bad merged columns: {list(merged.columns)}")
    if any(column.endswith(("_x", "_y")) for column in merged.columns):
        _fail("preloaded passthrough cache merge", f"merge suffix collision: {list(merged.columns)}")
    _pass("preloaded score columns coexist with missing materialized cabinet columns")


def main() -> int:
    checks = [
        check_latest_cabinet_resolves,
        check_cache_builder_is_materialized_path,
        check_missing_cache_fails_closed,
        check_runtime_uses_cache_for_cabinet,
        check_web_and_cli_entrypoints,
        check_interactive_order_prepares_cache_first,
        check_partitioned_cache_artifact_contract,
        check_preloaded_passthrough_columns_do_not_collide,
    ]
    failures = 0
    for check in checks:
        try:
            check()
        except Exception as exc:
            failures += 1
            if not isinstance(exc, AssertionError):
                print(f"[FAIL] {check.__name__}: {exc}")
    if failures:
        print(f"\n[FAIL] factor_cabinet feature cache verification failed: {failures}")
        return 1
    print("\n[PASS] factor_cabinet feature cache verification passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
