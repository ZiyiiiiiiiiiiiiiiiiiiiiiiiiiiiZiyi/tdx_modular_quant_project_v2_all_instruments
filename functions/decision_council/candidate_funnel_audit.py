"""Post-run reconciliation for the governance candidate-to-execution funnel."""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path


FUNNEL_COUNT_COLUMNS = (
    "universe_count", "proposal_symbol_count", "factor_valid_count",
    "instrument_type_pass_count", "universe_membership_pass_count",
    "trading_pass_count", "price_quality_pass_count", "liquidity_pass_count",
    "buy_quality_pass_count", "required_value_pass_count",
    "primary_score_pass_count", "score_percentile_pass_count",
    "candidate_limit_pass_count", "entry_confirmation_pass_count",
    "state_machine_role_pass_count", "risk_pass_count", "reputation_pass_count",
    "regime_pass_count", "cooldown_pass_count", "capital_pass_count",
    "ideal_portfolio_count", "order_count", "executed_buy_count",
)
FUNNEL_METADATA_COLUMNS = (
    "risk_stage_mode", "reputation_stage_mode", "regime_stage_mode",
    "candidate_detail_scope", "candidate_detail_count",
)


def terminal_block_reason(row: pd.Series) -> tuple[str, str, str]:
    """Return first stage, terminal reason, and all observed reasons."""
    entry_value = row.get("entry_confirmed", pd.NA)
    role_value = row.get("state_machine_role_pass", pd.NA)
    checks = (
        ("entry_confirmation", pd.notna(entry_value) and not bool(entry_value), row.get("entry_block_reason", "entry_not_confirmed")),
        ("state_machine_role", pd.notna(role_value) and not bool(role_value), row.get("state_machine_role_block_reason", "role_gate_failed")),
        ("cooldown", pd.notna(row.get("cooldown_active", pd.NA)) and bool(row.get("cooldown_active")), "cooldown_active"),
        ("position_state", str(row.get("position_state", "")).lower() in {"blocked", "cooldown", "exiting", "protecting_profit"}, row.get("position_state", "blocked")),
        ("capital", pd.notna(row.get("retail_executable", pd.NA)) and not bool(row.get("retail_executable")), row.get("retail_block_reason", "retail_not_executable")),
    )
    found = [(stage, str(reason or stage)) for stage, blocked, reason in checks if blocked]
    if not found:
        return "passed", "passed", ""
    return found[0][0], found[-1][1], "|".join(dict.fromkeys(reason for _, reason in found))


def build_candidate_rejection_detail(entry_audit: pd.DataFrame, *, decision_prefix: str = "gov_") -> pd.DataFrame:
    if entry_audit is None or entry_audit.empty:
        return pd.DataFrame()
    data = entry_audit.copy()
    data["date"] = pd.to_datetime(data.get("date"), errors="coerce")
    if "decision_id" not in data.columns:
        data["decision_id"] = data["date"].map(
            lambda value: f"{decision_prefix}{value.strftime('%Y%m%d')}" if pd.notna(value) else ""
        )
    classified = data.apply(terminal_block_reason, axis=1, result_type="expand")
    classified.columns = ["first_block_stage", "terminal_block_reason", "all_block_reasons"]
    data = pd.concat([data, classified], axis=1)
    data["pipeline_stage"] = np.where(data["first_block_stage"].eq("passed"), "capital_pass", "rejected")
    keep = [
        "decision_id", "date", "symbol", "pipeline_stage", "first_block_stage",
        "terminal_block_reason", "all_block_reasons", "primary_score",
        "entry_alpha_score", "entry_timing_score", "entry_liquidity_score",
        "entry_matrix_score", "entry_confirmed", "retail_executable",
        "state_machine_role_pass", "state_machine_role_block_reason", "cooldown_active",
        "one_lot_cash_required", "available_cash", "forward_return_5d",
        "forward_return_10d", "forward_return_20d",
    ]
    for column in keep:
        if column not in data.columns:
            data[column] = pd.NA
    return data[keep].sort_values(["date", "symbol"]).reset_index(drop=True)


def reconcile_funnel_daily(
    runtime_rows: pd.DataFrame,
    *,
    ideal_plan: pd.DataFrame,
    order_plan: pd.DataFrame,
    execution_ledger: pd.DataFrame,
) -> pd.DataFrame:
    data = runtime_rows.copy() if runtime_rows is not None else pd.DataFrame()
    if data.empty:
        return data
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["decision_id"] = data.get("decision_id", data["date"].dt.strftime("gov_%Y%m%d"))
    sources = (
        (ideal_plan, "decision_id", "ideal_portfolio_count", None),
        (order_plan, "decision_id", "order_count", None),
        (execution_ledger, "decision_id", "executed_buy_count", "buy"),
    )
    for frame, key, output, side in sources:
        if frame is None or frame.empty or key not in frame.columns:
            data[output] = 0
            continue
        sample = frame.copy()
        if side is not None and "side" in sample.columns:
            sample = sample[sample["side"].astype(str).str.lower().eq(side)]
        if output == "executed_buy_count" and "execution_status" in sample.columns:
            sample = sample[
                sample["execution_status"].astype(str).str.lower().isin({"filled", "executed"})
            ]
        counts = sample.groupby(key).size()
        data[output] = data["decision_id"].map(counts).fillna(0).astype(int)
    for column in FUNNEL_COUNT_COLUMNS:
        if column not in data.columns:
            data[column] = 0
        data[column] = pd.to_numeric(data[column], errors="coerce").fillna(0).astype(int)
    for column in FUNNEL_METADATA_COLUMNS:
        if column not in data.columns:
            data[column] = pd.NA
    ordered = ["decision_id", "date", *FUNNEL_COUNT_COLUMNS, *FUNNEL_METADATA_COLUMNS]
    return data[ordered].sort_values("date").reset_index(drop=True)


def summarize_funnel(daily: pd.DataFrame) -> pd.DataFrame:
    if daily is None or daily.empty:
        return pd.DataFrame()
    rows = []
    previous = None
    stage_notes = {
        "risk_pass_count": "score_or_size_only; not a standalone removal filter",
        "reputation_pass_count": "diagnostics_only; not a candidate admission filter",
        "regime_pass_count": "confirmation_or_exposure overlay; not a standalone removal filter",
        "capital_pass_count": "full count only when candidate detail scope covers all candidates",
    }
    for stage in FUNNEL_COUNT_COLUMNS:
        count = int(pd.to_numeric(daily[stage], errors="coerce").fillna(0).sum())
        rows.append({
            "stage": stage,
            "total_count": count,
            "rejected_from_previous": max(int(previous - count), 0) if previous is not None else 0,
            "pass_rate_from_previous": count / previous if previous and previous > 0 else np.nan,
            "stage_note": stage_notes.get(stage, ""),
        })
        previous = count
    return pd.DataFrame(rows)


def build_control_opportunity_cost(rejections: pd.DataFrame) -> pd.DataFrame:
    if rejections is None or rejections.empty:
        return pd.DataFrame()
    rejected = rejections[~rejections["first_block_stage"].eq("passed")].copy()
    rows = []
    for stage, group in rejected.groupby("first_block_stage", dropna=False):
        row = {"control_stage": stage, "rejected_count": int(len(group))}
        for horizon in (5, 10, 20):
            values = pd.to_numeric(group[f"forward_return_{horizon}d"], errors="coerce").dropna()
            row[f"sample_count_{horizon}d"] = int(len(values))
            row[f"mean_missed_return_{horizon}d"] = float(values.mean()) if not values.empty else np.nan
            row[f"positive_rate_{horizon}d"] = float(values.gt(0).mean()) if not values.empty else np.nan
            row[f"avoided_loss_mean_{horizon}d"] = float((-values[values < 0]).mean()) if (values < 0).any() else 0.0
            row[f"missed_gain_mean_{horizon}d"] = float(values[values > 0].mean()) if (values > 0).any() else 0.0
        rows.append(row)
    return pd.DataFrame(rows).sort_values("control_stage").reset_index(drop=True)


def build_entry_gate_summary(candidate_gates: pd.DataFrame) -> pd.DataFrame:
    """Summarize explicit candidate gate failures without double-counting totals."""
    if candidate_gates is None or candidate_gates.empty:
        return pd.DataFrame()
    data = candidate_gates.copy()
    gate_columns = [column for column in data.columns if column.endswith("_pass")]
    rows = []
    for gate in gate_columns:
        passed = data[gate].fillna(False).astype(bool)
        failed = ~passed
        rows.append({
            "gate": gate,
            "candidate_count": int(len(data)),
            "pass_count": int(passed.sum()),
            "fail_count": int(failed.sum()),
            "pass_rate": float(passed.mean()) if len(passed) else np.nan,
            "unique_first_failure_count": int(
                data.get("first_block_reason", pd.Series("", index=data.index)).astype(str).eq(gate.removesuffix("_pass")).sum()
            ),
        })
    return pd.DataFrame(rows).sort_values("gate").reset_index(drop=True)


def build_entry_gate_summary_from_csv_parts(paths, *, chunksize: int = 5000) -> pd.DataFrame:
    totals: dict[str, dict[str, int]] = {}
    for path in [Path(item) for item in paths]:
        try:
            iterator = pd.read_csv(path, chunksize=chunksize)
        except (OSError, pd.errors.EmptyDataError):
            continue
        for chunk in iterator:
            first_reason = chunk.get("first_block_reason", pd.Series("", index=chunk.index)).astype(str)
            for gate in (column for column in chunk.columns if column.endswith("_pass")):
                passed = chunk[gate].fillna(False).astype(bool)
                target = totals.setdefault(gate, {"candidate_count": 0, "pass_count": 0, "unique_first_failure_count": 0})
                target["candidate_count"] += int(len(chunk))
                target["pass_count"] += int(passed.sum())
                target["unique_first_failure_count"] += int(first_reason.eq(gate.removesuffix("_pass")).sum())
    rows = []
    for gate, values in totals.items():
        count = values["candidate_count"]
        passed = values["pass_count"]
        rows.append({
            "gate": gate, "candidate_count": count, "pass_count": passed,
            "fail_count": count - passed, "pass_rate": passed / count if count else np.nan,
            "unique_first_failure_count": values["unique_first_failure_count"],
        })
    return pd.DataFrame(rows).sort_values("gate").reset_index(drop=True) if rows else pd.DataFrame()


def build_control_trigger_summary(
    candidate_gates: pd.DataFrame,
    *,
    order_plan: pd.DataFrame,
    execution_ledger: pd.DataFrame,
) -> pd.DataFrame:
    gates = candidate_gates.copy() if candidate_gates is not None else pd.DataFrame()
    orders = order_plan.copy() if order_plan is not None else pd.DataFrame()
    executions = execution_ledger.copy() if execution_ledger is not None else pd.DataFrame()
    rows = []
    if not gates.empty:
        versions = gates.get("strategy_logic_version", pd.Series("production_v1", index=gates.index)).astype(str)
        active_probability = gates.get(
            "probability_gate_changed_decision", pd.Series(False, index=gates.index)
        ).fillna(False).astype(bool) & versions.ne("mainline_v2")
        rows.append({
            "control": "probability_gate",
            "evaluated_count": _true_count(gates, "probability_gate_evaluated"),
            "paper_trigger_count": _true_count(gates, "probability_gate_changed_decision"),
            "active_trigger_count": int(active_probability.sum()),
            "order_created_count": 0,
            "filled_count": 0,
        })
    exit_controls = (
        ("profit_giveback_exit", "paper_profit_giveback_exit", "profit_giveback_exit"),
        ("post_entry_failure_exit", "paper_post_entry_failure_exit", "post_entry_failure_exit"),
        ("signal_failure_exit", "paper_signal_failure_exit", "signal_failure_exit"),
        ("hard_stop_exit", "paper_hard_stop_exit", "hard_stop_exit"),
    )
    for control, paper_column, active_column in exit_controls:
        order_reason = orders.get("reason", pd.Series("", index=orders.index)).astype(str)
        fill_reason = executions.get("reason", pd.Series("", index=executions.index)).astype(str)
        fill_status = executions.get("execution_status", pd.Series("", index=executions.index)).astype(str).str.lower()
        rows.append({
            "control": control,
            "evaluated_count": int(len(gates)),
            "paper_trigger_count": _true_count(gates, paper_column),
            "active_trigger_count": _true_count(gates, active_column),
            "order_created_count": int(order_reason.eq(control).sum()),
            "filled_count": int((fill_reason.eq(control) & fill_status.eq("filled")).sum()),
        })
    return pd.DataFrame(rows)


def build_control_trigger_summary_from_csv_parts(
    paths,
    *,
    order_plan: pd.DataFrame,
    execution_ledger: pd.DataFrame,
    chunksize: int = 5000,
) -> pd.DataFrame:
    """Compute exact trigger counts from monthly parts without concatenating history."""
    totals: dict[str, dict[str, int]] = {}
    for path in paths:
        for chunk in pd.read_csv(path, chunksize=max(int(chunksize), 1)):
            partial = build_control_trigger_summary(
                chunk,
                order_plan=pd.DataFrame(),
                execution_ledger=pd.DataFrame(),
            )
            for row in partial.to_dict("records"):
                control = str(row["control"])
                target = totals.setdefault(
                    control,
                    {
                        "evaluated_count": 0,
                        "paper_trigger_count": 0,
                        "active_trigger_count": 0,
                    },
                )
                for column in target:
                    target[column] += int(row.get(column, 0) or 0)
    orders = order_plan.copy() if order_plan is not None else pd.DataFrame()
    executions = execution_ledger.copy() if execution_ledger is not None else pd.DataFrame()
    order_reason = orders.get("reason", pd.Series("", index=orders.index)).astype(str)
    fill_reason = executions.get("reason", pd.Series("", index=executions.index)).astype(str)
    fill_status = executions.get("execution_status", pd.Series("", index=executions.index)).astype(str).str.lower()
    rows = []
    for control, counts in totals.items():
        rows.append(
            {
                "control": control,
                **counts,
                "order_created_count": int(order_reason.eq(control).sum()),
                "filled_count": int((fill_reason.eq(control) & fill_status.eq("filled")).sum()),
                "audit_scope": "full_streamed_history",
            }
        )
    return pd.DataFrame(rows).sort_values("control").reset_index(drop=True) if rows else pd.DataFrame()


def _true_count(data: pd.DataFrame, column: str) -> int:
    if column not in data.columns:
        return 0
    return int(data[column].fillna(False).astype(bool).sum())


def build_exposure_reconciliation(exposure: pd.DataFrame) -> pd.DataFrame:
    if exposure is None or exposure.empty:
        return pd.DataFrame()
    data = exposure.copy()
    def numeric(name: str) -> pd.Series:
        source = data[name] if name in data.columns else pd.Series(0.0, index=data.index)
        return pd.to_numeric(source, errors="coerce").fillna(0.0)
    target = numeric("target_exposure")
    actual = numeric("actual_exposure")
    reported_gap = numeric("exposure_gap")
    data["reconciled_exposure_gap"] = target - actual
    data["reconciliation_error"] = data["reconciled_exposure_gap"] - reported_gap
    data["candidate_shortfall_flag"] = numeric("qualified_entry_count").le(0)
    data["capital_constraint_flag"] = numeric("retail_blocked_count").gt(0)
    data["lot_size_constraint_flag"] = numeric("retail_lot_cash_insufficient_count").gt(0)
    data["risk_constraint_flag"] = (
        data["risk_new_buy_block_applied"].fillna(False).astype(bool)
        if "risk_new_buy_block_applied" in data.columns
        else pd.Series(False, index=data.index)
    )
    keep = [
        "date", "decision_id", "target_exposure", "actual_exposure", "exposure_gap",
        "reconciled_exposure_gap", "reconciliation_error", "qualified_entry_count",
        "retail_blocked_count", "retail_lot_cash_insufficient_count",
        "candidate_shortfall_flag", "capital_constraint_flag", "lot_size_constraint_flag",
        "risk_constraint_flag", "catchup_block_reason", "exposure_authorization_block_reasons",
    ]
    for column in keep:
        if column not in data.columns:
            data[column] = pd.NA
    return data[keep].copy()
