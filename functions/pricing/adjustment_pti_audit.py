# -*- coding: utf-8 -*-
"""PIT adjustment-factor audit that blocks formal claims when evidence is incomplete."""
from __future__ import annotations

import pandas as pd


def build_adjustment_pti_quality_report(factors: pd.DataFrame, corporate_actions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    rows.append(_check("factor_rows_present", not factors.empty, f"factor_rows={len(factors)}"))
    required_action_dates = {"announcement_date", "ex_date", "revision_timestamp"}
    missing = sorted(required_action_dates - set(corporate_actions.columns))
    rows.append(
        _check(
            "announcement_to_ex_date_window_test",
            not missing and not corporate_actions.empty,
            f"missing_columns={missing}; corporate_action_rows={len(corporate_actions)}",
        )
    )
    rows.append(
        _check(
            "no_pre_ex_date_adjustment_test",
            False,
            "Requires provider PIT action timestamps and historical slice recomputation.",
        )
    )
    rows.append(
        _check(
            "ex_date_return_continuity_test",
            False,
            "Requires approved continuity thresholds and audited event samples.",
        )
    )
    rows.append(
        _check(
            "revision_impact_interval_report",
            False,
            "Requires provider revision history.",
        )
    )
    return pd.DataFrame(rows)


def _check(check, passed, detail):
    return {"check": check, "status": "passed" if passed else "blocked", "detail": detail}
