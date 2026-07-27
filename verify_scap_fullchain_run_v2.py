"""Reusable product-level verifier for a completed SCAP governance run."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def _check(condition: bool, label: str, detail: str = "") -> dict[str, object]:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f": {detail}" if detail else ""))
    return {"check": label, "passed": bool(condition), "detail": detail}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--expected-days", type=int, default=20)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    results: list[dict[str, object]] = []

    completion = json.loads((run_dir / "COMPLETE.json").read_text(encoding="utf-8"))
    checkpoint = json.loads((run_dir / "run_checkpoint.json").read_text(encoding="utf-8"))
    results.append(_check(completion.get("status") == "complete", "completion marker"))
    results.append(
        _check(
            int(completion.get("trading_days", -1)) == args.expected_days,
            "completion day count",
            str(completion.get("trading_days")),
        )
    )
    results.append(_check(checkpoint.get("status") == "complete", "checkpoint complete"))

    csv_paths = sorted(run_dir.glob("*.csv"))
    unreadable: list[str] = []
    zero_columns: list[str] = []
    frames: dict[str, pd.DataFrame] = {}
    for path in csv_paths:
        try:
            frame = pd.read_csv(path, low_memory=False)
            frames[path.name] = frame
            if len(frame.columns) == 0:
                zero_columns.append(path.name)
        except Exception as exc:  # product audit must report every malformed artifact
            unreadable.append(f"{path.name}: {exc}")
    results.append(_check(not unreadable, "all CSV artifacts readable", f"files={len(csv_paths)}"))
    results.append(_check(not zero_columns, "all CSV artifacts retain headers"))

    daily = frames["governance_daily_result.csv"]
    results.append(_check(len(daily) == args.expected_days, "daily ledger row count", str(len(daily))))
    results.append(_check(not daily["date"].duplicated().any(), "daily dates unique"))
    nav_error = (
        pd.to_numeric(daily["nominal_nav"], errors="coerce")
        - pd.to_numeric(daily["cash"], errors="coerce")
        - pd.to_numeric(daily["invested_value"], errors="coerce")
    ).abs()
    results.append(
        _check(float(nav_error.max()) <= 0.01, "NAV reconciliation", f"max_error={nav_error.max():.6f}")
    )
    target = pd.to_numeric(daily["target_exposure"], errors="coerce")
    results.append(_check(target.between(0.0, 1.0).all(), "target exposure bounded"))
    holdings = pd.to_numeric(daily["holding_count"], errors="coerce")
    configured = pd.to_numeric(daily["configured_max_positions"], errors="coerce")
    results.append(_check((holdings <= configured).all(), "position count bounded"))

    integrity = frames["governance_runtime_integrity_audit.csv"]
    results.append(
        _check(
            integrity["passed"].astype(str).str.lower().eq("true").all(),
            "runtime integrity audit",
            f"checks={len(integrity)}",
        )
    )

    execution = frames["governance_execution_ledger.csv"]
    if "fill_id" in execution.columns:
        filled = execution.loc[execution.get("execution_status", "").astype(str).eq("filled")]
        fill_ids = filled["fill_id"].dropna().astype(str)
        results.append(_check(not fill_ids.duplicated().any(), "fill IDs idempotent"))
    else:
        results.append(_check(execution.empty, "execution schema/no fill IDs consistent"))

    pending = frames["pending_order_ledger.csv"]
    order_plan = frames["executable_order_plan.csv"]
    selected_plan_keys = pd.DataFrame(columns=["decision_id", "symbol"])
    if (
        not order_plan.empty
        and {"decision_id", "symbol", "side", "action_plan_selected"}.issubset(
            order_plan.columns
        )
    ):
        selected_plan_keys = order_plan[
            order_plan["side"].astype(str).str.lower().eq("buy")
            & order_plan["action_plan_selected"].astype(str).str.lower().eq("true")
        ][["decision_id", "symbol"]].drop_duplicates()
    if "registration_key" in pending.columns:
        keys = pending["registration_key"].dropna().astype(str)
        results.append(_check(not keys.duplicated().any(), "pending registration keys unique"))
    else:
        results.append(_check(pending.empty, "pending schema/no registration keys consistent"))

    if not pending.empty and not selected_plan_keys.empty:
        selected_pending = pending.merge(
            selected_plan_keys,
            on=["decision_id", "symbol"],
            how="inner",
        )
        populated_pending_lineage = (
            selected_pending["action_plan_id"].fillna("").astype(str).str.len().gt(0)
            & selected_pending["action_proposal_id"].fillna("").astype(str).str.len().gt(0)
            & selected_pending["cash_reservation_id"].fillna("").astype(str).str.len().gt(0)
        )
        results.append(
            _check(
                populated_pending_lineage.all(),
                "selected pending orders preserve populated plan lineage",
                f"selected={len(selected_pending)}",
            )
        )

    if not execution.empty and not selected_plan_keys.empty:
        selected_fills = execution[
            execution["execution_status"].astype(str).str.lower().eq("filled")
        ].merge(
            selected_plan_keys,
            on=["decision_id", "symbol"],
            how="inner",
        )
        populated_fill_lineage = (
            selected_fills["action_plan_id"].fillna("").astype(str).str.len().gt(0)
            & selected_fills["action_proposal_id"].fillna("").astype(str).str.len().gt(0)
            & selected_fills["cash_reservation_id"].fillna("").astype(str).str.len().gt(0)
        )
        results.append(
            _check(
                populated_fill_lineage.all(),
                "selected fills preserve populated plan lineage",
                f"selected_fills={len(selected_fills)}",
            )
        )

    retail = frames["governance_retail_execution_diagnostics.csv"]
    if (
        not order_plan.empty
        and {"decision_id", "symbol", "side", "action_plan_selected"}.issubset(order_plan.columns)
        and {"decision_id", "symbol", "retail_block_reason"}.issubset(retail.columns)
    ):
        selected_buys = order_plan[
            order_plan["side"].astype(str).str.lower().eq("buy")
            & order_plan["action_plan_selected"].astype(str).str.lower().eq("true")
        ][["decision_id", "symbol"]].drop_duplicates()
        selected_retail = selected_buys.merge(
            retail[["decision_id", "symbol", "retail_block_reason"]],
            on=["decision_id", "symbol"],
            how="left",
        )
        legacy_state_vetoes = selected_retail[
            selected_retail["retail_block_reason"].fillna("").astype(str).eq(
                "position_state"
            )
        ]
        results.append(
            _check(
                legacy_state_vetoes.empty,
                "authorized ActionPlan has no legacy position-state veto",
                f"vetoes={len(legacy_state_vetoes)}",
            )
        )
    else:
        results.append(
            _check(
                order_plan.empty,
                "authorized ActionPlan position-state audit schema",
            )
        )

    numeric_infinite: list[str] = []
    for name, frame in frames.items():
        numeric = frame.select_dtypes(include=[np.number])
        if not numeric.empty and np.isinf(numeric.to_numpy(dtype=float, na_value=np.nan)).any():
            numeric_infinite.append(name)
    results.append(_check(not numeric_infinite, "no infinite numeric outputs"))

    summary = frames["governance_strategy_summary.csv"].iloc[0]
    results.append(
        _check(
            str(summary.get("experiment_sample_role")) == "development_audit",
            "20-day window labeled development-only",
        )
    )
    factor_status_path = run_dir / "holding_factor_curves" / "product_status.json"
    factor_status = json.loads(factor_status_path.read_text(encoding="utf-8"))
    workbook_path = Path(str(factor_status.get("workbook_path", "")))
    results.append(
        _check(
            factor_status.get("workbook_status") in {"ok", "complete"},
            "factor workbook built",
            str(factor_status.get("workbook_status")),
        )
    )
    results.append(_check(workbook_path.is_file(), "factor workbook saved", str(workbook_path)))

    failures = [item for item in results if not item["passed"]]
    report = {
        "run_dir": str(run_dir),
        "expected_days": args.expected_days,
        "csv_artifact_count": len(csv_paths),
        "checks": results,
        "passed": not failures,
        "failure_count": len(failures),
    }
    report_path = run_dir / "fullchain_product_verification_v2.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
