# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    GOVERNANCE_OUTPUT_DIR,
    PROCESSED_DIR,
    RESULT_DIR,
    STRATEGY_END_DATE,
    STRATEGY_START_DATE,
)
from functions.date_window import window_identity
from functions.report_builder import build_strategy_report, save_strategy_report
from functions.strategy_registry import STRATEGY_REGISTRY, list_strategy_names


def infer_weighting_mode(strategy_source: str) -> str:
    if strategy_source in {"technical", "research", "position_management"}:
        return "kelly_managed"
    if strategy_source == "governance":
        return "dynamic_governance"
    return "equal_weight"


def selection_metadata_from_frame(frame: pd.DataFrame, strategy_name: str) -> dict:
    spec = STRATEGY_REGISTRY.get(strategy_name)
    strategy_source = spec.source if spec is not None else "unknown"
    weighting_mode = infer_weighting_mode(strategy_source)
    price_basis = (
        frame["price_basis"].dropna().astype(str).iloc[0]
        if "price_basis" in frame.columns and not frame["price_basis"].dropna().empty
        else (
            frame["feature_price_source"].dropna().astype(str).iloc[0]
            if "feature_price_source" in frame.columns and not frame["feature_price_source"].dropna().empty
            else ("nominal_unadjusted" if weighting_mode != "equal_weight" else "adjusted_point_in_time")
        )
    )
    neutralization_mode = (
        frame["neutralization_mode"].dropna().astype(str).iloc[0]
        if "neutralization_mode" in frame.columns and not frame["neutralization_mode"].dropna().empty
        else ("not_applicable" if weighting_mode != "equal_weight" else "winsor_only")
    )
    ml_runtime_mode = (
        frame["ml_runtime_mode"].dropna().astype(str).iloc[0]
        if "ml_runtime_mode" in frame.columns and not frame["ml_runtime_mode"].dropna().empty
        else "not_applicable"
    )
    requested_model = (
        frame["requested_model"].dropna().astype(str).iloc[0]
        if "requested_model" in frame.columns and not frame["requested_model"].dropna().empty
        else ""
    )
    runtime_model = (
        frame["runtime_model"].dropna().astype(str).iloc[0]
        if "runtime_model" in frame.columns and not frame["runtime_model"].dropna().empty
        else ""
    )
    flags = []
    if "degradation_flags" in frame.columns:
        for value in frame["degradation_flags"].fillna("").astype(str):
            for flag in value.split("|"):
                flag = flag.strip()
                if flag and flag not in flags:
                    flags.append(flag)
    if not flags and weighting_mode == "equal_weight" and neutralization_mode != "industry_size_neutralized":
        flags.append("neutralization_disabled_or_partial")

    weights = pd.to_numeric(frame.get("weight", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    grouped = []
    if "rebalance_date" in frame.columns and not frame.empty:
        for _, group in frame.groupby("rebalance_date", sort=False):
            group_weights = pd.to_numeric(group.get("weight", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
            if group_weights.empty:
                continue
            ordered = group_weights.sort_values(ascending=False).reset_index(drop=True)
            sq = float(np.square(ordered).sum())
            grouped.append(
                (
                    float(ordered.iloc[0]) if len(ordered) else 0.0,
                    float(ordered.head(5).sum()) if len(ordered) else 0.0,
                    float(1.0 / sq) if sq > 0 else 0.0,
                )
            )
    top1 = float(np.mean([x[0] for x in grouped])) if grouped else (float(weights.max()) if not weights.empty else 0.0)
    top5 = float(np.mean([x[1] for x in grouped])) if grouped else (float(weights.sort_values(ascending=False).head(5).sum()) if not weights.empty else 0.0)
    effective_n = float(np.mean([x[2] for x in grouped])) if grouped else (float(1.0 / np.square(weights).sum()) if not weights.empty and float(np.square(weights).sum()) > 0 else 0.0)

    identity = window_identity(STRATEGY_START_DATE, STRATEGY_END_DATE)
    return {
        "strategy_source": strategy_source,
        "weighting_mode": weighting_mode,
        "price_basis": price_basis,
        "neutralization_mode": neutralization_mode,
        "ml_runtime_mode": ml_runtime_mode,
        "requested_model": requested_model,
        "runtime_model": runtime_model,
        "date_window": f"{identity['start_date'] or '-'} -> {identity['end_date'] or '-'}",
        "degradation_flags": "|".join(flags),
        "degradation_count": len(flags),
        "top1_weight": top1,
        "top5_weight_sum": top5,
        "effective_n": effective_n,
        "benchmark_status": "blocked: benchmark_excess_return requires an attached investable benchmark series",
    }


def backfill_selection_files():
    identity = window_identity(STRATEGY_START_DATE, STRATEGY_END_DATE)
    for strategy_name in list_strategy_names():
        path = PROCESSED_DIR / f"{strategy_name}.parquet"
        if not path.exists():
            continue
        frame = pd.read_parquet(path)
        metadata = selection_metadata_from_frame(frame, strategy_name)
        frame["strategy_name"] = strategy_name
        for key, value in metadata.items():
            if key in {"top1_weight", "top5_weight_sum", "effective_n", "degradation_count", "benchmark_status"}:
                continue
            frame[key] = value
        frame["configured_start_date"] = frame.get("configured_start_date", identity["start_date"])
        frame["configured_end_date"] = frame.get("configured_end_date", identity["end_date"])
        frame["date_window"] = metadata["date_window"]
        path.unlink(missing_ok=False)
        frame.to_parquet(path, index=False)
        print(f"Backfilled selection metadata: {path}")


def rebuild_backtest_summary():
    summary_path = RESULT_DIR / "backtest_strategy_summary.csv"
    if not summary_path.exists():
        raise FileNotFoundError(summary_path)
    summary = pd.read_csv(summary_path)
    rows = []
    for _, row in summary.iterrows():
        strategy_name = str(row["strategy"])
        selection_path = PROCESSED_DIR / f"{strategy_name}.parquet"
        metadata = selection_metadata_from_frame(pd.read_parquet(selection_path), strategy_name) if selection_path.exists() else {}
        enriched = row.to_dict()
        enriched.update(metadata)
        rows.append(enriched)
    rebuilt = pd.DataFrame(rows)
    source_order = {
        "rule": 0,
        "technical": 1,
        "research": 1,
        "position_management": 1,
        "governance": 2,
        "ml": 3,
        "classic_ml": 3,
        "quantum_inspired": 3,
        "unknown": 9,
    }
    rebuilt["report_category_order"] = rebuilt["strategy_source"].map(source_order).fillna(9)
    rebuilt = rebuilt.sort_values(["report_category_order", "composite_score"], ascending=[True, False]).reset_index(drop=True)
    rebuilt.to_csv(summary_path, index=False, encoding="utf-8-sig")
    save_strategy_report(build_strategy_report(rebuilt), RESULT_DIR / "strategy_diagnostic_report.md")
    print(f"Rebuilt summary/report: {summary_path}")


def backfill_governance_summary():
    governance_summary = GOVERNANCE_OUTPUT_DIR / "governance_strategy_summary.csv"
    if not governance_summary.exists():
        return None
    frame = pd.read_csv(governance_summary)
    defaults = {
        "strategy_source": "governance",
        "weighting_mode": "dynamic_governance",
        "price_basis": "nominal_unadjusted",
        "neutralization_mode": "not_applicable",
        "ml_runtime_mode": "not_applicable",
        "requested_model": "",
        "runtime_model": "",
        "benchmark_status": "blocked: governance benchmark proxy is safety-only, not an investable excess-return benchmark",
        "turnover_budget": pd.NA,
        "participation_rate": pd.NA,
        "capacity_passed_ratio": pd.NA,
        "portfolio_exposure_cap": pd.NA,
        "trading_freeze_trigger_count": 0,
        "trading_freeze_total_rebalance_periods": 0,
        "trading_freeze_period_lengths": "",
        "trading_freeze_min_exposure_cap": pd.NA,
        "trading_freeze_min_target_exposure": pd.NA,
        "emergency_deleveraging_trigger_count": 0,
        "emergency_deleveraging_total_rebalance_periods": 0,
        "emergency_deleveraging_period_lengths": "",
        "emergency_deleveraging_min_exposure_cap": pd.NA,
        "emergency_deleveraging_min_target_exposure": pd.NA,
    }
    for column, default in defaults.items():
        if column not in frame.columns:
            frame[column] = default
    frame.to_csv(governance_summary, index=False, encoding="utf-8-sig")
    return frame


def main():
    backfill_selection_files()
    rebuild_backtest_summary()
    governance_df = backfill_governance_summary()
    if governance_df is not None:
        save_strategy_report(
            build_strategy_report(pd.DataFrame(), governance_summary_df=governance_df, report_title="Governance Strategy Report"),
            GOVERNANCE_OUTPUT_DIR / "governance_strategy_report.md",
        )
        print("Refreshed governance report.")


if __name__ == "__main__":
    main()
