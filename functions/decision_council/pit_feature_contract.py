"""Point-in-time availability checks for slow and event feature families."""
from __future__ import annotations

import pandas as pd


PIT_RESTRICTED_TOKENS = ("valuation", "profitability", "investment", "cashflow", "growth", "event")


def audit_pit_feature_availability(frame: pd.DataFrame, feature_columns) -> pd.DataFrame:
    features = [str(column) for column in feature_columns if any(token in str(column).lower() for token in PIT_RESTRICTED_TOKENS)]
    if not features:
        return pd.DataFrame(columns=["feature", "status", "violation_count", "row_count"])
    decision = pd.to_datetime(frame.get("date"), errors="coerce")
    available = pd.to_datetime(frame.get("pit_available_at"), errors="coerce") if "pit_available_at" in frame else pd.Series(pd.NaT, index=frame.index)
    rows = []
    for feature in features:
        present = feature in frame.columns
        populated = frame[feature].notna() if present else pd.Series(False, index=frame.index)
        missing_timestamp = populated & available.isna()
        late = populated & available.notna() & decision.notna() & available.gt(decision)
        violations = int((missing_timestamp | late).sum())
        rows.append({"feature": feature, "status": "pass" if present and violations == 0 else "fail",
                     "violation_count": violations, "row_count": int(populated.sum())})
    return pd.DataFrame(rows)


def pit_eligible_features(frame: pd.DataFrame, feature_columns) -> tuple[str, ...]:
    audit = audit_pit_feature_availability(frame, feature_columns)
    failed = set(audit.loc[audit["status"].ne("pass"), "feature"].astype(str)) if not audit.empty else set()
    return tuple(str(column) for column in feature_columns if str(column) not in failed)
