"""Regression checks for the bounded PIT size-factor coverage bridge."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from functions.decision_council.factor_cabinet_feature_cache import (
    SIZE_FACTOR_PIT_PROXY_AGE_COLUMN,
    SIZE_FACTOR_PIT_PROXY_COLUMNS,
    SIZE_FACTOR_PIT_PROXY_USED_COLUMN,
    repair_bounded_size_factor_coverage,
)
from functions.decision_council.factor_runtime_audit import (
    _audit_authorized_role_daily_coverage,
)


def _fixture() -> pd.DataFrame:
    rows = []
    observations = (
        ("2026-01-02", 10.0, 20.0),
        ("2026-01-05", 11.0, 19.0),
        ("2026-01-06", 12.0, 18.0),
    )
    for date, first_price, second_price in observations:
        for symbol, price, initial_cap in (
            ("sh600000", first_price, 1000.0),
            ("sz000001", second_price, 4000.0),
        ):
            observed_cap = initial_cap if date == "2026-01-02" else np.nan
            row = {
                "date": pd.Timestamp(date),
                "symbol": symbol,
                "close_nominal": price,
                "stabilized_total_cap": observed_cap,
                "stabilized_float_cap": observed_cap / 2.0,
            }
            for column in SIZE_FACTOR_PIT_PROXY_COLUMNS:
                row[column] = 0.1 if date == "2026-01-02" else np.nan
            rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    repaired = repair_bounded_size_factor_coverage(_fixture(), max_sessions=1)
    first_bridge = repaired["date"].eq(pd.Timestamp("2026-01-05"))
    expired = repaired["date"].eq(pd.Timestamp("2026-01-06"))
    assert repaired.loc[first_bridge, SIZE_FACTOR_PIT_PROXY_USED_COLUMN].all()
    assert repaired.loc[first_bridge, SIZE_FACTOR_PIT_PROXY_AGE_COLUMN].eq(1).all()
    assert repaired.loc[first_bridge, list(SIZE_FACTOR_PIT_PROXY_COLUMNS)].notna().all().all()
    assert not repaired.loc[expired, SIZE_FACTOR_PIT_PROXY_USED_COLUMN].any()
    assert repaired.loc[expired, list(SIZE_FACTOR_PIT_PROXY_COLUMNS)].isna().all().all()

    sh = repaired.loc[first_bridge & repaired["symbol"].eq("sh600000")].iloc[0]
    # Last total shares = 1000 / 10 = 100; current cap = 100 * 11.
    assert np.isclose(sh["cand_size_total_cap_neg"], -np.log1p(1100.0), rtol=1e-6)
    # The smaller reconstructed company receives the higher cross-sectional rank.
    assert np.isclose(sh["cand_grid_base_rank__size_total_neg"], 1.0)

    context = SimpleNamespace(
        model_feature_map={"size_model": "cand_size_total_cap_neg"},
        primary_role_map={"size_model": "entry_alpha"},
        family_map={"size_model": "size"},
    )
    coverage, failures = _audit_authorized_role_daily_coverage(
        repaired,
        context=context,
        decision_start="2026-01-02",
        decision_end="2026-01-05",
    )
    assert failures == []
    assert coverage["entry_alpha"]["minimum_active_model_count"] == 1
    _, expired_failures = _audit_authorized_role_daily_coverage(
        repaired,
        context=context,
        decision_start="2026-01-02",
        decision_end="2026-01-06",
    )
    assert any("2026-01-06" in failure for failure in expired_failures)
    print("[PASS] bounded size-factor PIT proxy reprices within the limit")
    print("[PASS] proxy expires and preserves the runtime coverage block")
    print("[PASS] repaired values satisfy the authorized-role daily audit")


if __name__ == "__main__":
    main()
