"""Acceptance audit for the simplified SCAP twenty-session contract."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def check(name: str, condition: bool, detail: str = "") -> None:
    if not bool(condition):
        raise AssertionError(f"{name}: {detail}")
    suffix = f" | {detail}" if detail else ""
    print(f"[PASS] {name}{suffix}")


def read_csv(run_dir: Path, name: str) -> pd.DataFrame:
    return pd.read_csv(run_dir / name, low_memory=False)


def numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()

    complete = json.loads((run_dir / "COMPLETE.json").read_text(encoding="utf-8"))
    daily = read_csv(run_dir, "governance_daily_result.csv")
    proposals = read_csv(run_dir, "governance_action_proposal_ledger.csv")
    plans = read_csv(run_dir, "governance_action_plan_ledger.csv")
    orders = read_csv(run_dir, "executable_order_plan.csv")
    pending = read_csv(run_dir, "pending_order_ledger.csv")
    executions = read_csv(run_dir, "governance_execution_ledger.csv")
    accounts = read_csv(run_dir, "governance_account_audit_ledger.csv")

    check("twenty-session run completed", complete.get("status") == "complete" and len(daily) == 20)
    required_semantics = {
        "strategic_exposure_target", "strategic_exposure_lower_bound",
        "strategic_exposure_upper_bound", "hard_risk_exposure_ceiling",
        "attainable_exposure_ceiling", "optimizer_planned_exposure",
        "actual_exposure", "strategic_exposure_gap", "attainable_exposure_gap",
        "execution_exposure_gap",
    }
    check("exposure semantics are explicit", required_semantics.issubset(daily.columns))
    strategic_gap = np.maximum(
        numeric(daily, "strategic_exposure_target") - numeric(daily, "actual_exposure"), 0.0
    )
    attainable_gap = np.maximum(
        np.minimum(
            numeric(daily, "strategic_exposure_target"),
            numeric(daily, "attainable_exposure_ceiling"),
        ) - numeric(daily, "actual_exposure"),
        0.0,
    )
    execution_gap = np.maximum(
        numeric(daily, "optimizer_planned_exposure") - numeric(daily, "actual_exposure"), 0.0
    )
    check("strategic exposure gap recomputes", np.allclose(strategic_gap, numeric(daily, "strategic_exposure_gap"), atol=1e-12))
    check("attainable exposure gap recomputes", np.allclose(attainable_gap, numeric(daily, "attainable_exposure_gap"), atol=1e-12))
    check("execution exposure gap recomputes", np.allclose(execution_gap, numeric(daily, "execution_exposure_gap"), atol=1e-12))
    check(
        "hard risk ceilings are respected",
        (numeric(daily, "actual_hard_risk_excess").fillna(0.0) <= 1e-12).all()
        and (numeric(daily, "planned_hard_risk_excess").fillna(0.0) <= 1e-12).all(),
    )

    for name, frame in (("proposal", proposals), ("plan", plans)):
        lineage = {"event_id", "input_hash", "formula_version", "record_status"}
        check(f"{name} lineage columns persist", lineage.issubset(frame.columns))
        check(f"{name} event ids are populated", frame["event_id"].astype(str).str.len().gt(0).all())
        check(f"{name} event ids are unique", frame["event_id"].astype(str).is_unique)
    check("plan ledger stores rejected detail externally", "rejected_proposals" not in plans.columns and plans["rejected_detail_storage"].eq("governance_action_proposal_ledger").all())

    selected = proposals[proposals["selected_by_plan"].astype(bool)].copy()
    check("at least one economic proposal is selected", not selected.empty, f"selected={len(selected)}")
    check("selected proposals pass the economic gate", selected["economic_order_pass"].astype(bool).all())
    selected_net_authority = numeric(selected, "robust_net_profit_amount") - numeric(selected, "authority_penalty_amount")
    check("selected proposal remains positive after authority haircut", selected_net_authority.gt(0.0).all())
    check(
        "selected proposal cost share stays within hard ceiling",
        numeric(selected, "lifecycle_cost_to_gross_profit_ratio").le(0.60 + 1e-12).all(),
    )

    buys = orders[orders["side"].astype(str).str.lower().eq("buy")].copy()
    ordinary = buys[buys["reason"].astype(str).isin(["normal_buy", "confirmed_entry_buy"])]
    recovery = buys[buys["reason"].astype(str).eq("exposure_catchup_buy")]
    monthly_dates = set(daily.loc[daily["allow_normal_rebalance"].astype(bool), "date"].astype(str))
    recovery_authorized = daily["catchup_allowed"].astype(bool)
    if "post_mandatory_recovery_authorized" in daily.columns:
        recovery_authorized = recovery_authorized | daily[
            "post_mandatory_recovery_authorized"
        ].astype(bool)
    recovery_dates = set(
        daily.loc[
            recovery_authorized
            & ~daily["allow_normal_rebalance"].astype(bool), "date"
        ].astype(str)
    )
    check("ordinary buys use monthly authority", set(ordinary["decision_date"].astype(str)).issubset(monthly_dates))
    check("recovery buys use recovery authority", set(recovery["decision_date"].astype(str)).issubset(recovery_dates))
    if not recovery.empty:
        counts = recovery.groupby(recovery["decision_date"].astype(str))["symbol"].nunique()
        exposure = recovery.groupby(recovery["decision_date"].astype(str))["delta_weight"].apply(
            lambda values: pd.to_numeric(values, errors="coerce").clip(lower=0.0).sum()
        )
        recovery_limits = daily.set_index(daily["date"].astype(str))
        name_limits = numeric(
            recovery_limits,
            "post_mandatory_recovery_max_new_names_today",
        ).reindex(counts.index)
        exposure_limits = numeric(
            recovery_limits,
            "post_mandatory_recovery_max_buy_exposure_today",
        ).reindex(exposure.index)
        check(
            "recovery names respect the post-mandatory conditional-floor budget",
            counts.le(name_limits + 1e-12).all(),
        )
        check(
            "recovery exposure respects the post-mandatory conditional-floor budget",
            exposure.le(exposure_limits + 1e-12).all(),
        )
        recovery_pending = pending[pending["reason"].astype(str).eq("exposure_catchup_buy")]
        check(
            "every recovery plan is preserved in pending-order state",
            set(recovery["decision_id"].astype(str)).issubset(
                set(recovery_pending["decision_id"].astype(str))
            ),
        )
        check(
            "recovery pending orders expire next session",
            recovery_pending["order_execution_policy"].eq("next_session_only").all()
            and numeric(recovery_pending, "maximum_age_sessions").eq(1).all(),
        )

    check("account ledger reconciles", numeric(accounts, "reconciliation_error").abs().max() <= 1e-9)
    check(
        "executed fills preserve plan lineage",
        executions.empty
        or (
            executions["action_plan_id"].astype(str).str.len().gt(0).all()
            and executions["action_proposal_id"].astype(str).str.len().gt(0).all()
        ),
    )
    check("the full chain creates holdings", numeric(daily, "holding_count").max() > 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
