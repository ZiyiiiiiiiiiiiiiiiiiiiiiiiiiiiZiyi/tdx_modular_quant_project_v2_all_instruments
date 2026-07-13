"""Verify productized pre-screen candidate factor cache and governance loading."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import (
    GOVERNANCE_PRE_SCREEN_FACTOR_CACHE_LOOKBACK_DAYS,
    GOVERNANCE_PRE_SCREEN_SELECTED_ALPHA_MODELS,
)
from functions.alpha_bundles import ALPHA_BUNDLE_REGISTRY
from functions.decision_council.candidate_factor_cache import (
    build_pre_screen_candidate_factor_cache,
    candidate_factor_cache_paths,
    load_pre_screen_candidate_factor_cache,
    pre_screen_candidate_raw_columns,
)
from functions.decision_council.factor_source import resolve_factor_source


def _expect(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def main() -> int:
    failures: list[str] = []
    target_start = pd.Timestamp("2021-01-04")
    target_end = pd.Timestamp("2021-01-08")
    cache_start = target_start - pd.Timedelta(days=int(GOVERNANCE_PRE_SCREEN_FACTOR_CACHE_LOOKBACK_DAYS) + 90)
    cache_end = target_end
    models = ALPHA_BUNDLE_REGISTRY.get_alpha_model_names("pre_screen_promote_bundle")
    raw_columns = pre_screen_candidate_raw_columns(models)

    parquet_path, manifest_path = build_pre_screen_candidate_factor_cache(
        cache_start,
        cache_end,
        alpha_models=models,
        allowed_instrument_types=("stock",),
        symbol_scope="all",
    )
    _expect(parquet_path.exists(), "candidate cache parquet should exist", failures)
    _expect(manifest_path.exists(), "candidate cache manifest should exist", failures)

    cache = load_pre_screen_candidate_factor_cache(
        target_start - pd.Timedelta(days=60),
        target_end,
        alpha_models=models,
    )
    _expect(not cache.empty, "candidate cache slice should not be empty", failures)
    _expect(set(raw_columns).issubset(cache.columns), "candidate cache should contain all selected raw columns", failures)
    _expect(len(models) == len(GOVERNANCE_PRE_SCREEN_SELECTED_ALPHA_MODELS) == 28, "pre-screen bundle should contain fixed 28 models", failures)

    try:
        resolve_factor_source(
            factor_source="legacy_bundle",
            alpha_bundle="pre_screen_promote_bundle",
        )
    except ValueError:
        pass
    else:
        failures.append("retired pre_screen bundle must not enter governance as legacy_bundle")

    expected_path, expected_manifest = candidate_factor_cache_paths(cache_start, cache_end)
    _expect(parquet_path == expected_path, "cache path should be deterministic", failures)
    _expect(manifest_path == expected_manifest, "manifest path should be deterministic", failures)

    if failures:
        print("Pre-screen candidate cache verification failed.")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Pre-screen candidate cache verification passed.")
    print(f"cache_parquet={parquet_path}")
    print(f"cache_manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
