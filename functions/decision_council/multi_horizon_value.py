"""Comparable, return-unit value contract for holdings and challengers.

Ranking scores and percentiles are deliberately excluded: they are ordinal and
cannot be subtracted from costs expressed as returns.  Replacement decisions
may only consume rows whose forecast and conservative bound share a horizon.
"""
from __future__ import annotations

import pandas as pd


SUPPORTED_HORIZONS = (5, 10, 20)


def attach_multi_horizon_value_contract(candidates: pd.DataFrame) -> pd.DataFrame:
    data = candidates.copy()
    for horizon in SUPPORTED_HORIZONS:
        expected_source = f"expected_edge_{horizon}d"
        conservative_source = f"conservative_expected_edge_{horizon}d"
        expected = _numeric(data, expected_source)
        conservative = _numeric(data, conservative_source)
        available = expected.notna()
        bound_available = available & conservative.notna()

        data[f"expected_alpha_{horizon}d"] = expected
        data[f"conservative_alpha_{horizon}d"] = conservative.where(bound_available)
        data[f"forecast_uncertainty_{horizon}d"] = (expected - conservative).clip(lower=0.0).where(bound_available)
        data[f"value_available_{horizon}d"] = available
        data[f"value_bound_available_{horizon}d"] = bound_available
        data[f"value_source_{horizon}d"] = pd.Series(
            "unavailable", index=data.index, dtype="object"
        ).where(~available, expected_source)
        data.loc[bound_available, f"value_source_{horizon}d"] = (
            expected_source + "+" + conservative_source
        )

    chosen_horizon = pd.Series(pd.NA, index=data.index, dtype="Int64")
    chosen_expected = pd.Series(float("nan"), index=data.index, dtype=float)
    chosen_lcb = pd.Series(float("nan"), index=data.index, dtype=float)
    # An authorized medium-horizon ML model may explicitly own replacement
    # value.  Without that treatment-effect authorization, retain the locked
    # rule hierarchy and keep 20-day ML estimates paper-only.
    preferred = pd.to_numeric(
        data.get("replacement_value_preferred_horizon_days", pd.Series(pd.NA, index=data.index)),
        errors="coerce",
    )
    medium_authorized = data.get(
        "ml_medium_value_authorized", pd.Series(False, index=data.index, dtype="boolean")
    ).astype("boolean").fillna(False).astype(bool)
    preferred_usable = medium_authorized & preferred.eq(20) & data["value_bound_available_20d"]
    chosen_horizon.loc[preferred_usable] = 20
    chosen_expected.loc[preferred_usable] = data.loc[preferred_usable, "expected_alpha_20d"]
    chosen_lcb.loc[preferred_usable] = data.loc[preferred_usable, "conservative_alpha_20d"]
    for horizon in (10, 5, 20):
        usable = chosen_horizon.isna() & data[f"value_bound_available_{horizon}d"]
        chosen_horizon.loc[usable] = horizon
        chosen_expected.loc[usable] = data.loc[usable, f"expected_alpha_{horizon}d"]
        chosen_lcb.loc[usable] = data.loc[usable, f"conservative_alpha_{horizon}d"]

    data["comparable_value_horizon_days"] = chosen_horizon
    data["comparable_expected_alpha"] = chosen_expected
    data["comparable_alpha_lcb"] = chosen_lcb
    data["comparable_value_available"] = chosen_horizon.notna()
    data["comparable_value_contract"] = "same_horizon_return_units_v1"
    return data


def comparable_pair(left: pd.Series, right: pd.Series) -> bool:
    """True only when two rows carry bounded forecasts for the same horizon."""
    left_h = pd.to_numeric(pd.Series([left.get("comparable_value_horizon_days")]), errors="coerce").iloc[0]
    right_h = pd.to_numeric(pd.Series([right.get("comparable_value_horizon_days")]), errors="coerce").iloc[0]
    return bool(
        pd.notna(left_h)
        and pd.notna(right_h)
        and int(left_h) == int(right_h)
        and bool(left.get("comparable_value_available", False))
        and bool(right.get("comparable_value_available", False))
    )


def _numeric(data: pd.DataFrame, column: str) -> pd.Series:
    if column not in data.columns:
        return pd.Series(float("nan"), index=data.index, dtype=float)
    return pd.to_numeric(data[column], errors="coerce")
