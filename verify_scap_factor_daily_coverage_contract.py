"""Regression checks for trade-authorized factor daily coverage."""
from __future__ import annotations

from types import MappingProxyType

import pandas as pd

from functions.decision_council.factor_runtime_audit import build_factor_runtime_audit
from functions.decision_council.factor_source import FactorSourceSpec


def _spec(tmp_path) -> FactorSourceSpec:
    cabinet = tmp_path / "factor_cabinet.json"
    cabinet.write_text(
        '{"factors":[{"factor_name":"strict_size","role":"entry_alpha"}]}',
        encoding="utf-8",
    )
    return FactorSourceSpec(
        factor_source="selected_factor_cabinet",
        factor_cabinet_run_id="coverage_fixture",
        factor_cabinet_path=str(cabinet),
        factor_count=1,
        model_feature_map={"strict_size": "strict_size_col"},
        role_map={"strict_size": "entry_alpha"},
        module_map={"strict_size": "size"},
        family_map={"strict_size": "size"},
        strict_entry_alpha_map={"strict_size": True},
    )


def main() -> int:
    from tempfile import TemporaryDirectory
    from pathlib import Path

    with TemporaryDirectory() as directory:
        spec = _spec(Path(directory))
        valid = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-05-18", "2026-05-18", "2026-05-19"]),
                "symbol": ["a", "b", "a"],
                "strict_size_col": [1.0, 2.0, 3.0],
            }
        )
        passed = build_factor_runtime_audit(
            spec,
            available_columns=valid.columns,
            feature_frame=valid,
            decision_start="2026-05-18",
            decision_end="2026-05-19",
        )
        assert passed.data_coverage_contract_verified
        assert not passed.fallback_detected
        assert passed.authorized_role_daily_coverage["entry_alpha"]["last_valid_date"] == "2026-05-19"
        assert passed.authorized_role_daily_coverage["entry_alpha"]["configured_family_count"] == 1
        assert passed.authorized_role_daily_coverage["entry_alpha"]["minimum_active_family_count"] == 1

        broken = valid.copy()
        broken.loc[broken["date"].eq(pd.Timestamp("2026-05-19")), "strict_size_col"] = pd.NA
        failed = build_factor_runtime_audit(
            spec,
            available_columns=broken.columns,
            feature_frame=broken,
            decision_start="2026-05-18",
            decision_end="2026-05-19",
        )
        assert failed.fallback_detected
        assert failed.fallback_reason == "authorized_factor_daily_coverage_incomplete"
        assert failed.authorized_role_daily_coverage["entry_alpha"]["first_invalid_date"] == "2026-05-19"
        assert failed.coverage_failures
    print("[PASS] trade-authorized factor coverage fails closed on an all-NaN day")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
