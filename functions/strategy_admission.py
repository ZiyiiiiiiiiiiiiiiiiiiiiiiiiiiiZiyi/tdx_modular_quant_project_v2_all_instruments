"""Binary V6 strategy admission without manual override."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import STRATEGY_ADMISSION_REPORT_CSV, V6_FORMAL_STRATEGY_CANDIDATES
from functions.data_integrity import data_verified


DEFAULT_THRESHOLDS = {
    "min_independent_events": 30,
    "min_net_return": 0.0,
    "min_information_ratio": 0.0,
    "max_drawdown": 0.25,
    "max_failed_order_ratio": 0.20,
}


def build_strategy_admission_report(
    metrics: pd.DataFrame,
    *,
    event_density: pd.DataFrame | None = None,
    thresholds: dict | None = None,
) -> pd.DataFrame:
    thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    metric_map = (
        metrics.set_index("strategy_id").to_dict("index")
        if not metrics.empty and "strategy_id" in metrics.columns
        else {}
    )
    density_map = {}
    if event_density is not None and not event_density.empty:
        density_map = (
            event_density.groupby("strategy_id")["independent_events"].sum().to_dict()
        )
    verified = data_verified()
    rows = []
    for strategy_id in V6_FORMAL_STRATEGY_CANDIDATES:
        row = metric_map.get(strategy_id, {})
        checks = {
            "data_verified": verified,
            "events": float(density_map.get(strategy_id, 0)) >= thresholds["min_independent_events"],
            "net_return": float(row.get("net_total_return", float("-inf"))) > thresholds["min_net_return"],
            "information_ratio": float(row.get("information_ratio", float("-inf"))) > thresholds["min_information_ratio"],
            "drawdown": abs(float(row.get("max_drawdown", float("inf")))) <= thresholds["max_drawdown"],
            "execution": float(row.get("failed_order_ratio", float("inf"))) <= thresholds["max_failed_order_ratio"],
            "parameter_stability": bool(row.get("parameter_stability_passed", False)),
            "calibration": bool(row.get("calibration_passed", False)),
            "capacity": bool(row.get("capacity_passed", False)),
        }
        passed = all(checks.values())
        rows.append(
            {
                "strategy_id": strategy_id,
                "admission_status": "PASS" if passed else "FAIL",
                "formal_weight_enabled": bool(passed),
                "failed_checks": "|".join(name for name, ok in checks.items() if not ok),
                **{f"check_{name}": bool(ok) for name, ok in checks.items()},
            }
        )
    return pd.DataFrame(rows)


def save_strategy_admission_report(metrics, *, event_density=None, output_path=STRATEGY_ADMISSION_REPORT_CSV):
    report = build_strategy_admission_report(metrics, event_density=event_density)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(path, index=False, encoding="utf-8-sig")
    return path
