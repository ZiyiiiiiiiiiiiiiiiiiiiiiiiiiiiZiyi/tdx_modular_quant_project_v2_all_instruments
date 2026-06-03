"""Daily governance monitoring and deterministic rollback recommendations."""
from __future__ import annotations

import pandas as pd


def evaluate_daily_rollback(exposure_ledger: pd.DataFrame, *, safety_ledger: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return auditable rollback decisions; callers decide whether to execute them."""
    if exposure_ledger.empty:
        return pd.DataFrame(columns=["date", "rollback_required", "rollback_reason", "rollback_target"])
    data = exposure_ledger.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    safety = safety_ledger.copy() if safety_ledger is not None else pd.DataFrame()
    if not safety.empty:
        date_col = "decision_date" if "decision_date" in safety.columns else "date"
        safety["date"] = pd.to_datetime(safety[date_col], errors="coerce")
        keep = [column for column in ["date", "risk_level_lag_days"] if column in safety.columns]
        data = data.merge(safety[keep].drop_duplicates("date", keep="last"), on="date", how="left")
    rows = []
    for row in data.to_dict(orient="records"):
        reasons = []
        if abs(_number(row.get("reconciliation_error"))) > 1e-8:
            reasons.append("account_reconciliation_error")
        if int(_number(row.get("missing_price_position_count"))) > 0:
            reasons.append("missing_price_mark")
        if int(_number(row.get("risk_level_lag_days"))) > 1:
            reasons.append("safety_proxy_stale")
        if _number(row.get("unresolved_safety_exposure")) > 0.05:
            reasons.append("unresolved_safety_exposure")
        rows.append(
            {
                "date": row["date"],
                "rollback_required": bool(reasons),
                "rollback_reason": "|".join(reasons),
                "rollback_target": "rules_based_president",
            }
        )
    return pd.DataFrame(rows)


def _number(value):
    return 0.0 if value is None or pd.isna(value) else float(value)
