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
    max_positions: int | None = None,
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
    return pd.DataFrame(rows)


def _row(check: str, passed: bool, detail: str) -> dict:
    return {"check": check, "passed": bool(passed), "detail": str(detail)}
