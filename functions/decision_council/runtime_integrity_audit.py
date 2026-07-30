"""Post-run integrity checks for governance decisions, fills, and accounting."""
from __future__ import annotations

import pandas as pd


ALLOWED_EXECUTION_STATUSES = frozenset({
    "filled", "pending", "partially_filled", "blocked", "cancelled", "expired",
})


def build_runtime_integrity_audit(
    *,
    execution_ledger: pd.DataFrame,
    account_audit: pd.DataFrame,
    daily_result: pd.DataFrame | None = None,
    holdings_ledger: pd.DataFrame | None = None,
    position_state_ledger: pd.DataFrame | None = None,
    max_positions: int | None = None,
    action_proposal_ledger: pd.DataFrame | None = None,
    action_plan_ledger: pd.DataFrame | None = None,
    order_plan_ledger: pd.DataFrame | None = None,
) -> pd.DataFrame:
    rows = []
    trades = execution_ledger.copy() if execution_ledger is not None else pd.DataFrame()
    if trades.empty:
        rows.extend([
            _row("execution_status_contract", True, "no execution rows"),
            _row("filled_share_conservation", True, "no execution rows"),
            _row("signal_before_execution", True, "no execution rows"),
        ])
    else:
        status = trades.get("execution_status", pd.Series("", index=trades.index)).fillna("").astype(str).str.lower()
        unknown = sorted(set(status) - set(ALLOWED_EXECUTION_STATUSES))
        rows.append(_row("execution_status_contract", not unknown, f"unknown_statuses={unknown}"))
        filled = trades[status.eq("filled")].copy()
        executed = pd.to_numeric(filled.get("executed_shares", pd.Series(0.0, index=filled.index)), errors="coerce").fillna(0.0)
        target = pd.to_numeric(filled.get("target_shares", pd.Series(0.0, index=filled.index)), errors="coerce").fillna(0.0)
        remaining = pd.to_numeric(filled.get("remaining_shares", target - executed), errors="coerce").fillna(target - executed)
        share_error = (target - executed - remaining).abs()
        rows.append(_row(
            "filled_share_conservation",
            bool((executed.gt(0.0) & share_error.le(1e-8)).all()),
            f"filled={len(filled)}, max_share_error={float(share_error.max()) if len(share_error) else 0.0}",
        ))
        signal = pd.to_datetime(filled.get("signal_date", pd.Series(pd.NaT, index=filled.index)), errors="coerce")
        execution = pd.to_datetime(filled.get("trade_date", pd.Series(pd.NaT, index=filled.index)), errors="coerce")
        known = signal.notna() & execution.notna()
        bad_timing = known & execution.le(signal)
        rows.append(_row(
            "signal_before_execution",
            bool(not bad_timing.any()),
            f"known={int(known.sum())}, invalid={int(bad_timing.sum())}",
        ))
        required_timing = {
            "signal_date", "decision_timestamp", "next_trading_day",
            "trade_date", "execution_price_basis",
        }
        missing_timing = sorted(required_timing - set(filled.columns))
        if missing_timing:
            rows.append(_row("execution_timing_contract", False, f"missing={missing_timing}"))
        else:
            decision_ts = pd.to_datetime(filled["decision_timestamp"], errors="coerce")
            next_day = pd.to_datetime(filled["next_trading_day"], errors="coerce")
            basis = filled["execution_price_basis"].fillna("").astype(str).str.strip()
            valid = (
                decision_ts.notna() & execution.notna() & next_day.notna()
                & execution.gt(decision_ts)
                & next_day.eq(execution)
                & basis.ne("")
            )
            rows.append(_row(
                "execution_timing_contract",
                bool(valid.all()),
                f"filled={len(filled)}, invalid={int((~valid).sum())}",
            ))
        if "order_id" in filled.columns:
            duplicate_fills = int(filled["order_id"].astype(str).duplicated().sum())
            rows.append(_row("unique_filled_order_id", duplicate_fills == 0, f"duplicates={duplicate_fills}"))
        pair_id = filled.get("replacement_pair_id", pd.Series("", index=filled.index)).fillna("").astype(str)
        paired = filled[pair_id.ne("")].copy()
        orphan_buys = 0
        if not paired.empty:
            for _, group in paired.groupby("replacement_pair_id", sort=False):
                sides = set(group["side"].astype(str).str.lower())
                if "buy" in sides and "sell" not in sides:
                    orphan_buys += 1
        rows.append(_row(
            "replacement_pair_execution_contract",
            orphan_buys == 0,
            f"paired_fills={len(paired)}, orphan_buy_pairs={orphan_buys}",
        ))

    accounts = account_audit.copy() if account_audit is not None else pd.DataFrame()
    if accounts.empty:
        rows.append(_row("account_nav_reconciliation", False, "account audit missing"))
    else:
        error = pd.to_numeric(accounts.get("reconciliation_error", pd.Series(float("nan"), index=accounts.index)), errors="coerce")
        passed = error.notna() & error.abs().le(1e-8)
        rows.append(_row(
            "account_nav_reconciliation",
            bool(passed.all()),
            f"rows={len(accounts)}, failed={int((~passed).sum())}, max_abs_error={float(error.abs().max())}",
        ))
    daily = daily_result.copy() if daily_result is not None else pd.DataFrame()
    if max_positions in (None, "", 0):
        rows.append(_row("position_limit_contract", True, "max_positions not configured"))
    elif daily.empty or "holding_count" not in daily.columns:
        rows.append(_row("position_limit_contract", False, "daily holding_count missing"))
    else:
        observed = pd.to_numeric(daily["holding_count"], errors="coerce")
        violations = observed.gt(int(max_positions))
        rows.append(_row(
            "position_limit_contract",
            bool(observed.notna().all() and not violations.any()),
            (
                f"configured={int(max_positions)}, max_observed="
                f"{int(observed.max()) if observed.notna().any() else 'missing'}, "
                f"violation_days={int(violations.sum())}"
            ),
        ))
    hard_cap_column = (
        "hard_exposure_ceiling"
        if daily_result is not None
        and "hard_exposure_ceiling" in daily_result.columns
        else "effective_target_exposure_cap"
    )
    exposure_columns = {"date", "actual_exposure", hard_cap_column}
    if daily.empty or not exposure_columns.issubset(daily.columns):
        rows.append(_row(
            "execution_exposure_authorization",
            False,
            f"missing={sorted(exposure_columns - set(daily.columns))}",
        ))
    else:
        exposure_daily = daily.copy()
        exposure_daily["date"] = pd.to_datetime(exposure_daily["date"], errors="coerce")
        exposure_daily = exposure_daily.sort_values("date")
        actual = pd.to_numeric(exposure_daily["actual_exposure"], errors="coerce")
        # Today's opening/settled holdings are produced by the preceding
        # decision. Compare them with that decision's executable cap. A small
        # absolute allowance covers overnight price gaps, not sizing mistakes.
        authorized = pd.to_numeric(
            exposure_daily[hard_cap_column],
            errors="coerce",
        ).shift(1)
        comparable = actual.notna() & authorized.notna()
        base_tolerance = 0.02
        tolerance = pd.Series(base_tolerance, index=exposure_daily.index, dtype=float)
        holding_granularity = (
            holdings_ledger.copy()
            if holdings_ledger is not None
            else pd.DataFrame()
        )
        if (
            not holding_granularity.empty
            and {"date", "account_weight"}.issubset(holding_granularity.columns)
        ):
            holding_granularity["date"] = pd.to_datetime(
                holding_granularity["date"],
                errors="coerce",
            )
            holding_granularity["account_weight"] = pd.to_numeric(
                holding_granularity["account_weight"],
                errors="coerce",
            )
            minimum_lot_weight = (
                holding_granularity[
                    holding_granularity["account_weight"].gt(0.0)
                ]
                .groupby("date")["account_weight"]
                .min()
            )
            mapped = exposure_daily["date"].map(minimum_lot_weight)
            # A small-capital account cannot trim less than one held lot.
            # Bound this allowance at ten percentage points so a genuine
            # sizing violation cannot be hidden by one very large position.
            lot_allowance = mapped.clip(lower=base_tolerance, upper=0.10)
            tolerance = lot_allowance.fillna(base_tolerance)
        excess = actual - authorized
        violations = comparable & excess.gt(tolerance + 1e-12)
        rows.append(_row(
            "execution_exposure_authorization",
            bool(not violations.any()),
            (
                f"comparable_days={int(comparable.sum())}, "
                f"violation_days={int(violations.sum())}, "
                f"max_excess={float(excess[comparable].max()) if comparable.any() else 'missing'}, "
                f"max_granularity_allowance={float(tolerance[comparable].max()) if comparable.any() else 'missing'}, "
                f"base_overnight_gap_tolerance={base_tolerance}"
            ),
        ))
    proposals = (
        action_proposal_ledger.copy()
        if action_proposal_ledger is not None
        else pd.DataFrame()
    )
    plans = (
        action_plan_ledger.copy()
        if action_plan_ledger is not None
        else pd.DataFrame()
    )
    if proposals.empty and plans.empty:
        rows.append(_row("action_lineage_contract", True, "no Lean action rows"))
    elif proposals.empty or plans.empty:
        rows.append(_row(
            "action_lineage_contract",
            False,
            "proposal or plan ledger missing",
        ))
    else:
        selected = proposals[
            proposals.get(
                "selected_by_plan",
                pd.Series(False, index=proposals.index),
            ).fillna(False).astype(bool)
        ].copy()
        selected_ids = set(selected["proposal_id"].astype(str))
        order_plans = (
            order_plan_ledger.copy()
            if order_plan_ledger is not None
            else trades
        )
        order_ids = set(
            order_plans.get(
                "action_proposal_id",
                pd.Series(dtype=str),
            ).dropna().astype(str)
        )
        order_ids.discard("")
        selected_without_order = selected_ids - order_ids
        filled_ids = set()
        if not trades.empty:
            filled_mask = trades.get(
                "execution_status",
                pd.Series("", index=trades.index),
            ).fillna("").astype(str).str.lower().eq("filled")
            filled_ids = set(
                trades.loc[filled_mask].get(
                    "action_proposal_id",
                    pd.Series(dtype=str),
                ).dropna().astype(str)
            )
            filled_ids.discard("")
        filled_without_selection = filled_ids - selected_ids
        plan_counts = plans.groupby("decision_id").size()
        duplicate_plan_decisions = int(plan_counts.gt(1).sum())
        rows.append(_row(
            "action_lineage_contract",
            bool(
                not selected_without_order
                and not filled_without_selection
                and duplicate_plan_decisions == 0
            ),
            (
                f"proposals={len(proposals)}, selected={len(selected)}, "
                f"selected_without_order={len(selected_without_order)}, "
                f"filled_without_selection={len(filled_without_selection)}, "
                f"duplicate_plan_decisions={duplicate_plan_decisions}"
            ),
        ))
    holdings = holdings_ledger.copy() if holdings_ledger is not None else pd.DataFrame()
    states = position_state_ledger.copy() if position_state_ledger is not None else pd.DataFrame()
    required = {"date", "symbol"}
    if holdings.empty:
        rows.append(_row("held_state_coverage", True, "no holding rows"))
    elif not required.issubset(holdings.columns) or not required.issubset(states.columns):
        rows.append(_row("held_state_coverage", False, "holding/state date-symbol columns missing"))
    else:
        holdings["date"] = pd.to_datetime(holdings["date"], errors="coerce")
        holdings["symbol"] = holdings["symbol"].astype(str)
        if "entry_date" in holdings.columns:
            entry_date = pd.to_datetime(holdings["entry_date"], errors="coerce")
            holdings = holdings[entry_date.isna() | entry_date.lt(holdings["date"])]
        expected = holdings[["date", "symbol"]].dropna().drop_duplicates()
        states["date"] = pd.to_datetime(states["date"], errors="coerce")
        states["symbol"] = states["symbol"].astype(str)
        if "held" in states.columns:
            held = states["held"].fillna(False).astype(bool)
            states = states[held]
        observed = states[["date", "symbol"]].dropna().drop_duplicates()
        missing = expected.merge(observed, on=["date", "symbol"], how="left", indicator=True)
        missing_count = int(missing["_merge"].eq("left_only").sum())
        rows.append(_row(
            "held_state_coverage",
            missing_count == 0,
            f"expected_overnight_holding_rows={len(expected)}, missing_state_rows={missing_count}",
        ))
        score_columns = [
            column for column in (
                "cabinet_native_final_score", "comparable_expected_alpha",
                "comparable_alpha_lcb", "comparable_value_horizon_days",
            ) if column in states.columns
        ]
        joined = expected.merge(states, on=["date", "symbol"], how="left")
        logic = joined.get(
            "entry_logic_version",
            joined.get("strategy_logic_version", pd.Series("", index=joined.index)),
        ).fillna("").astype(str)
        v3 = logic.str.startswith("mainline_v3")
        if not v3.any():
            rows.append(_row("held_score_coverage", True, "no v3 overnight holdings"))
        elif not score_columns:
            rows.append(_row("held_score_coverage", False, "v3 held rows have no comparable score fields"))
        else:
            complete = joined.loc[v3, score_columns].notna().all(axis=1)
            rows.append(_row(
                "held_score_coverage", bool(complete.all()),
                f"v3_held_rows={int(v3.sum())}, complete_rows={int(complete.sum())}, fields={'|'.join(score_columns)}",
            ))
    return pd.DataFrame(rows)


def _row(check: str, passed: bool, detail: str) -> dict:
    return {"check": check, "passed": bool(passed), "detail": str(detail)}
