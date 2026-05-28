# -*- coding: utf-8 -*-
"""Audit roadmap readiness from code and real data artifacts."""
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from config import (
    ADJUSTMENT_FACTORS_PARQUET,
    BACKTEST_SUMMARY_V2_CSV,
    CORPORATE_ACTIONS_PARQUET,
    FEATURE_DAILY_PARQUET,
    FORMAL_MODE_NAME,
    MARKET_CAP_PARQUET,
    REPORT_DIR,
    RESEARCH_RUN_MODE,
)


def audit_completion():
    rows = []
    rows.append(_file_check("P0-0", "corporate_actions", CORPORATE_ACTIONS_PARQUET))
    rows.append(_validated_factor_check())
    rows.append(_feature_price_check())
    rows.append(_orders_check())
    rows.append(_file_check("P0-3", "baseline_summary_v2", BACKTEST_SUMMARY_V2_CSV))
    rows.append(_file_check("P1-0", "market_cap_history", MARKET_CAP_PARQUET))
    rows.append({
        "stage": "P0b",
        "check": "formal_mode_enabled",
        "status": "pass" if RESEARCH_RUN_MODE == FORMAL_MODE_NAME else "blocked",
        "detail": f"RESEARCH_RUN_MODE={RESEARCH_RUN_MODE}",
    })
    return pd.DataFrame(rows)


def _file_check(stage, check, path):
    path = Path(path)
    return {
        "stage": stage,
        "check": check,
        "status": "pass" if path.exists() else "missing",
        "detail": str(path),
    }


def _validated_factor_check():
    if not ADJUSTMENT_FACTORS_PARQUET.exists():
        return {"stage": "P0-0", "check": "validated_adjustment_factors", "status": "missing",
                "detail": str(ADJUSTMENT_FACTORS_PARQUET)}
    factors = pd.read_parquet(ADJUSTMENT_FACTORS_PARQUET)
    valid = factors.get("factor_source_validated", pd.Series(False, index=factors.index)).fillna(False)
    symbols = factors.loc[valid, "symbol"].nunique()
    return {"stage": "P0-0", "check": "validated_adjustment_factors",
            "status": "pass" if symbols > 0 else "blocked", "detail": f"validated_symbols={symbols}"}


def _feature_price_check():
    if not FEATURE_DAILY_PARQUET.exists():
        return {"stage": "P0-1", "check": "point_in_time_prices", "status": "missing",
                "detail": str(FEATURE_DAILY_PARQUET)}
    columns = pq.read_schema(FEATURE_DAILY_PARQUET).names
    features = pd.read_parquet(FEATURE_DAILY_PARQUET, columns=["feature_price_source"]) \
        if "feature_price_source" in columns else pd.DataFrame()
    ok = not features.empty and (features["feature_price_source"] == "adjusted_point_in_time").any()
    return {"stage": "P0-1", "check": "point_in_time_prices",
            "status": "pass" if ok else "blocked", "detail": "requires rebuilt factor-attached features"}


def _orders_check():
    ledgers = list(Path("results").glob("backtest_orders_*.csv"))
    return {
        "stage": "P0-2",
        "check": "order_ledgers_and_constraints",
        "status": "partial" if ledgers else "missing",
        "detail": (
            f"ledger_count={len(ledgers)}; order accounting exists, "
            "but formal ST/board limit and multi-day retry data remain required"
        ),
    }


if __name__ == "__main__":
    output = REPORT_DIR / "roadmap_completion_audit.csv"
    report = audit_completion()
    report.to_csv(output, index=False, encoding="utf-8-sig")
    print(report.to_string(index=False))
    print(f"Saved roadmap audit: {output}")
