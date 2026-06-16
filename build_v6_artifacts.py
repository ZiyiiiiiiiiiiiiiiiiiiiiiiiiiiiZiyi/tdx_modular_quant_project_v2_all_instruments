"""Build V6 governance artifacts from currently available exploratory outputs."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from config import (
    EVENT_DENSITY_REPORT_CSV,
    PROCESSED_DIR,
    REPORT_DIR,
    RESULT_DIR,
    STRATEGY_ADMISSION_REPORT_CSV,
    V6_FORMAL_STRATEGY_CANDIDATES,
    V6_RUNTIME_MONITORING_CSV,
    V6_RUNTIME_STATUS_JSON,
    V6_STRATEGY_TARGET_HORIZONS,
)
from functions.data_integrity import data_verified, save_data_integrity_artifacts
from functions.event_statistics import build_event_density_report, build_independent_events
from functions.strategy_admission import save_strategy_admission_report


def main():
    integrity_outputs = save_data_integrity_artifacts()
    density = build_selection_proxy_event_density()
    EVENT_DENSITY_REPORT_CSV.parent.mkdir(parents=True, exist_ok=True)
    density.to_csv(EVENT_DENSITY_REPORT_CSV, index=False, encoding="utf-8-sig")
    metrics = load_strategy_metrics()
    admission_path = save_strategy_admission_report(
        metrics,
        event_density=density,
        output_path=STRATEGY_ADMISSION_REPORT_CSV,
    )
    monitoring_path, status_path = save_runtime_monitoring(metrics, density)
    for path in [*integrity_outputs, EVENT_DENSITY_REPORT_CSV, admission_path, monitoring_path, status_path]:
        print("Saved:", path)


def build_selection_proxy_event_density() -> pd.DataFrame:
    frames = []
    for strategy_id in V6_FORMAL_STRATEGY_CANDIDATES:
        calibration_path = REPORT_DIR / f"v6_calibration_{strategy_id}.csv"
        if calibration_path.exists():
            calibration = pd.read_csv(calibration_path)
            valid = calibration[pd.to_numeric(calibration.get("sample_count"), errors="coerce").notna()]
            if not valid.empty:
                latest = valid.iloc[-1]
                frames.append(
                    pd.DataFrame(
                        [
                            {
                                "strategy_id": strategy_id,
                                "year": "cumulative_through_2021",
                                "raw_signal_rows": int(latest["sample_count"]),
                                "independent_events": int(latest["sample_count"]),
                                "independent_trade_dates": pd.NA,
                                "unique_symbols": pd.NA,
                                "density_status": "ok",
                                "event_source": "mature_independent_calibration",
                                "formal_usable": False,
                            }
                        ]
                    )
                )
                continue
        path = PROCESSED_DIR / f"{strategy_id}.parquet"
        if not path.exists():
            continue
        frame = pd.read_parquet(path)
        date_col = "rebalance_date" if "rebalance_date" in frame.columns else "date"
        if date_col not in frame.columns or "symbol" not in frame.columns:
            continue
        signals = frame[[date_col, "symbol"]].copy()
        signals["strategy_id"] = strategy_id
        signals["direction"] = "long"
        signals["signal_timestamp"] = pd.to_datetime(signals[date_col], errors="coerce") + pd.Timedelta(hours=15, minutes=30)
        signals["tradeable_timestamp"] = signals["signal_timestamp"] + pd.offsets.BDay(1)
        horizon = int(V6_STRATEGY_TARGET_HORIZONS[strategy_id])
        signals["reference_date"] = signals["tradeable_timestamp"] + pd.offsets.BDay(horizon)
        signals["return_horizon_days"] = horizon
        frames.append(signals)
    if not frames:
        return pd.DataFrame(
            columns=[
                "strategy_id",
                "year",
                "raw_signal_rows",
                "independent_events",
                "independent_trade_dates",
                "unique_symbols",
                "density_status",
                "event_source",
                "formal_usable",
            ]
        )
    if all("signal_timestamp" not in frame.columns for frame in frames):
        return pd.concat(frames, ignore_index=True)
    completed = [
        frame
        for frame in frames
        if "signal_timestamp" not in frame.columns
    ]
    signal_frames = [
        frame
        for frame in frames
        if "signal_timestamp" in frame.columns
    ]
    if not signal_frames:
        return pd.concat(completed, ignore_index=True)
    events = build_independent_events(pd.concat(signal_frames, ignore_index=True))
    density = build_event_density_report(events)
    density["event_source"] = "saved_selection_proxy"
    density["formal_usable"] = False
    return pd.concat([*completed, density], ignore_index=True, sort=False)


def load_strategy_metrics() -> pd.DataFrame:
    records = []
    for strategy_id in V6_FORMAL_STRATEGY_CANDIDATES:
        selection_path = PROCESSED_DIR / f"{strategy_id}.parquet"
        metrics_path = RESULT_DIR / f"backtest_metrics_{strategy_id}.csv"
        if not selection_path.exists() or not metrics_path.exists():
            continue
        selection = pd.read_parquet(selection_path)
        if selection.empty:
            continue
        if metrics_path.stat().st_mtime < selection_path.stat().st_mtime:
            continue
        metric_frame = pd.read_csv(metrics_path)
        record = {"strategy_id": strategy_id}
        record.update(dict(zip(metric_frame["metric"], metric_frame["value"])))
        records.append(record)
    metrics = pd.DataFrame(records)
    if metrics.empty:
        return pd.DataFrame(columns=["strategy_id"])
    metrics["information_ratio"] = pd.to_numeric(
        metrics.get("information_ratio"), errors="coerce"
    )
    metrics["parameter_stability_passed"] = False
    metrics["calibration_passed"] = False
    metrics["capacity_passed"] = False
    return metrics


def save_runtime_monitoring(metrics: pd.DataFrame, density: pd.DataFrame) -> tuple[Path, Path]:
    rows = []
    admission = (
        pd.read_csv(STRATEGY_ADMISSION_REPORT_CSV)
        if STRATEGY_ADMISSION_REPORT_CSV.exists()
        else pd.DataFrame()
    )
    for strategy_id in V6_FORMAL_STRATEGY_CANDIDATES:
        metric = metrics[metrics["strategy_id"] == strategy_id]
        admitted = admission[admission["strategy_id"] == strategy_id]
        strategy_density = density[density["strategy_id"] == strategy_id]
        rows.append(
            {
                "strategy_id": strategy_id,
                "admission_status": admitted.iloc[0]["admission_status"] if not admitted.empty else "FAIL",
                "net_total_return": metric.iloc[0].get("net_total_return") if not metric.empty else pd.NA,
                "max_drawdown": metric.iloc[0].get("max_drawdown") if not metric.empty else pd.NA,
                "turnover_ratio": metric.iloc[0].get("turnover_ratio") if not metric.empty else pd.NA,
                "transaction_cost_ratio": metric.iloc[0].get("transaction_cost_ratio") if not metric.empty else pd.NA,
                "failed_order_ratio": metric.iloc[0].get("failed_order_ratio") if not metric.empty else pd.NA,
                "independent_event_proxy_count": int(strategy_density["independent_events"].sum()) if not strategy_density.empty else 0,
                "data_verified": data_verified(),
                "formal_event_density_available": False,
            }
        )
    monitoring = pd.DataFrame(rows)
    V6_RUNTIME_MONITORING_CSV.parent.mkdir(parents=True, exist_ok=True)
    monitoring.to_csv(V6_RUNTIME_MONITORING_CSV, index=False, encoding="utf-8-sig")
    status = {
        "data_verified": data_verified(),
        "formal_strategy_pass_count": int((monitoring["admission_status"] == "PASS").sum()),
        "formal_strategy_fail_count": int((monitoring["admission_status"] == "FAIL").sum()),
        "event_density_source": "saved_selection_proxy",
        "event_density_formal_usable": False,
        "next_required_action": "Build raw independent events from the full PIT feature universe.",
    }
    V6_RUNTIME_STATUS_JSON.write_text(
        json.dumps(status, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return V6_RUNTIME_MONITORING_CSV, V6_RUNTIME_STATUS_JSON


if __name__ == "__main__":
    main()
