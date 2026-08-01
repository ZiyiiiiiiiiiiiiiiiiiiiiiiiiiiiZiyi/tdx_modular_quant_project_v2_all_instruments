"""Post-run SCAP profit-objective diagnostics in actual account currency."""
from __future__ import annotations

import numpy as np
import pandas as pd


SCAP_PROFIT_OBJECTIVE_VERSION = "scap_counterfactual_forward_profit_audit_v2"


def build_scap_profit_objective_audit(entry_audit: pd.DataFrame) -> pd.DataFrame:
    """Measure 20-day net yuan outcomes without feeding future returns to selection."""
    if entry_audit is None or entry_audit.empty:
        return pd.DataFrame()
    data = entry_audit.copy()
    market_notional = pd.to_numeric(
        data.get("one_lot_market_notional", pd.Series(np.nan, index=data.index)),
        errors="coerce",
    )
    legacy_cash_notional = pd.to_numeric(
        data.get("one_lot_cash_required", pd.Series(np.nan, index=data.index)),
        errors="coerce",
    )
    notional = market_notional.combine_first(legacy_cash_notional)
    notional_basis = pd.Series(
        np.where(
            market_notional.notna(),
            "one_lot_market_notional",
            "legacy_one_lot_cash_required_fallback",
        ),
        index=data.index,
    )
    forward = pd.to_numeric(
        data.get("forward_return_20d", pd.Series(np.nan, index=data.index)),
        errors="coerce",
    )
    cost_rate = pd.to_numeric(
        data.get(
            "scap_estimated_round_trip_cost_rate",
            pd.Series(np.nan, index=data.index),
        ),
        errors="coerce",
    )
    data["scap_counterfactual_forward_net_return_20d_audit"] = forward - cost_rate
    data["scap_counterfactual_forward_net_profit_yuan_20d_audit"] = (
        notional * data["scap_counterfactual_forward_net_return_20d_audit"]
    )
    # Deprecated compatibility aliases.  These are not fill-ledger realized PnL.
    data["scap_realized_net_return_20d_audit"] = data[
        "scap_counterfactual_forward_net_return_20d_audit"
    ]
    data["scap_realized_net_profit_yuan_20d_audit"] = data[
        "scap_counterfactual_forward_net_profit_yuan_20d_audit"
    ]
    data["scap_profit_objective_observed"] = (
        notional.gt(0.0)
        & forward.notna()
        & cost_rate.notna()
    )
    data["scap_profit_objective_selected"] = data.get(
        "scap_optimizer_selected", pd.Series(False, index=data.index)
    ).astype("boolean").fillna(False).astype(bool)
    data["scap_profit_objective_version"] = SCAP_PROFIT_OBJECTIVE_VERSION
    data["scap_profit_objective_runtime_authority"] = (
        "audit_only_future_20d_not_available_at_decision_time"
    )
    data["scap_profit_objective_notional_basis"] = notional_basis
    data["scap_realized_field_compatibility_status"] = (
        "deprecated_alias_not_fill_ledger_realized_pnl"
    )
    columns = [
        "decision_id",
        "date",
        "symbol",
        "scap_profit_objective_selected",
        "one_lot_cash_required",
        "forward_return_20d",
        "scap_estimated_round_trip_cost_rate",
        "scap_counterfactual_forward_net_return_20d_audit",
        "scap_counterfactual_forward_net_profit_yuan_20d_audit",
        "scap_realized_net_return_20d_audit",
        "scap_realized_net_profit_yuan_20d_audit",
        "scap_profit_objective_observed",
        "scap_candidate_utility",
        "primary_score",
        "scap_profit_objective_version",
        "scap_profit_objective_runtime_authority",
        "scap_profit_objective_notional_basis",
        "scap_realized_field_compatibility_status",
    ]
    for column in columns:
        if column not in data.columns:
            data[column] = pd.NA
    return data[columns]


def summarize_scap_profit_objective(audit: pd.DataFrame) -> pd.DataFrame:
    if audit is None or audit.empty:
        return pd.DataFrame()
    observed = audit[
        audit["scap_profit_objective_observed"]
        .astype("boolean")
        .fillna(False)
        .astype(bool)
    ].copy()
    rows = []
    for label, group in (
        ("optimizer_selected", observed[observed["scap_profit_objective_selected"]]),
        ("not_selected", observed[~observed["scap_profit_objective_selected"]]),
        ("all_observed", observed),
    ):
        pnl = pd.to_numeric(
            group.get("scap_counterfactual_forward_net_profit_yuan_20d_audit"),
            errors="coerce",
        ).dropna()
        rows.append(
            {
                "cohort": label,
                "sample_count": int(len(pnl)),
                "mean_net_profit_yuan_20d": (
                    float(pnl.mean()) if not pnl.empty else np.nan
                ),
                "median_net_profit_yuan_20d": (
                    float(pnl.median()) if not pnl.empty else np.nan
                ),
                "positive_net_profit_rate_20d": (
                    float(pnl.gt(0.0).mean()) if not pnl.empty else np.nan
                ),
                "runtime_activation_eligible": False,
                "activation_block_reason": (
                    "requires_pre_registered_rolling_oos_expected_profit_calibration"
                ),
                "scap_profit_objective_version": SCAP_PROFIT_OBJECTIVE_VERSION,
            }
        )
    return pd.DataFrame(rows)
