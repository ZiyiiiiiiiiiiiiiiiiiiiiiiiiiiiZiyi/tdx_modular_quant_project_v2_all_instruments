"""Auditable treatment effect of ML ranking versus Cabinet Native ranking."""
from __future__ import annotations

import numpy as np
import pandas as pd


def attach_rank_treatment(
    candidates: pd.DataFrame,
    *,
    top_k: int,
    rule_score_column: str = "cabinet_native_final_score",
    hybrid_score_column: str = "hybrid_final_score",
) -> pd.DataFrame:
    """Attach candidate-level rank changes without changing any trading decision."""
    required = {"symbol", rule_score_column, hybrid_score_column}
    missing = sorted(required - set(candidates.columns))
    if missing:
        raise ValueError(f"ML treatment audit is missing columns: {missing}")
    output = candidates.copy()
    group_keys = ["date"] if "date" in output.columns else None
    if group_keys:
        output["ml_rule_rank"] = output.groupby(group_keys, sort=False)[rule_score_column].rank(
            ascending=False, method="first"
        )
        output["ml_hybrid_rank"] = output.groupby(group_keys, sort=False)[hybrid_score_column].rank(
            ascending=False, method="first"
        )
    else:
        output["ml_rule_rank"] = output[rule_score_column].rank(ascending=False, method="first")
        output["ml_hybrid_rank"] = output[hybrid_score_column].rank(ascending=False, method="first")
    output["ml_rank_improvement"] = output["ml_rule_rank"] - output["ml_hybrid_rank"]
    limit = max(int(top_k), 1)
    output["ml_rule_top_k"] = output["ml_rule_rank"].le(limit)
    output["ml_hybrid_top_k"] = output["ml_hybrid_rank"].le(limit)
    output["ml_treatment_group"] = np.select(
        [
            ~output["ml_rule_top_k"] & output["ml_hybrid_top_k"],
            output["ml_rule_top_k"] & ~output["ml_hybrid_top_k"],
            output["ml_rank_improvement"].gt(0),
            output["ml_rank_improvement"].lt(0),
        ],
        ["promoted_into_top_k", "demoted_out_of_top_k", "rank_promoted", "rank_demoted"],
        default="unchanged",
    )
    return output


def daily_treatment_summary(treated: pd.DataFrame, *, top_k: int) -> pd.DataFrame:
    """Summarize whether ML had enough authority to change the executable shortlist."""
    if treated is None or treated.empty:
        return pd.DataFrame()
    dates = treated["date"] if "date" in treated else pd.Series(pd.NaT, index=treated.index)
    rows = []
    for date, group in treated.assign(_audit_date=dates).groupby("_audit_date", dropna=False, sort=True):
        rule_symbols = set(group.loc[group["ml_rule_top_k"], "symbol"].astype(str))
        hybrid_symbols = set(group.loc[group["ml_hybrid_top_k"], "symbol"].astype(str))
        denominator = max(min(len(rule_symbols), len(hybrid_symbols), max(int(top_k), 1)), 1)
        rows.append({
            "date": date,
            "candidate_count": int(len(group)),
            "top_k": int(top_k),
            "top_k_overlap_count": int(len(rule_symbols & hybrid_symbols)),
            "top_k_overlap_rate": float(len(rule_symbols & hybrid_symbols) / denominator),
            "promoted_into_top_k_count": int(len(hybrid_symbols - rule_symbols)),
            "demoted_out_of_top_k_count": int(len(rule_symbols - hybrid_symbols)),
            "mean_absolute_rank_change": float(group["ml_rank_improvement"].abs().mean()),
            "maximum_absolute_rank_change": float(group["ml_rank_improvement"].abs().max()),
            "ml_changed_top_k": bool(rule_symbols != hybrid_symbols),
        })
    return pd.DataFrame(rows)


def mature_treatment_effect(
    treatment_ledger: pd.DataFrame,
    labels: pd.DataFrame,
) -> pd.DataFrame:
    """Compare the realized net alpha of synchronized rule and hybrid Top-K baskets."""
    required = {"date", "symbol", "ml_rule_top_k", "ml_hybrid_top_k"}
    missing = sorted(required - set(treatment_ledger.columns))
    if missing:
        raise ValueError(f"treatment ledger is missing columns: {missing}")
    label_required = {"date", "symbol", "future_excess_log_return_net", "label_maturity_date"}
    label_missing = sorted(label_required - set(labels.columns))
    if label_missing:
        raise ValueError(f"treatment labels are missing columns: {label_missing}")
    merged = treatment_ledger.merge(
        labels.loc[:, list(label_required)], on=["date", "symbol"], how="left"
    )
    merged = merged.dropna(subset=["future_excess_log_return_net"])
    rows = []
    for date, group in merged.groupby("date", sort=True):
        rule = group.loc[group["ml_rule_top_k"], "future_excess_log_return_net"]
        hybrid = group.loc[group["ml_hybrid_top_k"], "future_excess_log_return_net"]
        promoted = group.loc[group["ml_treatment_group"].eq("promoted_into_top_k"), "future_excess_log_return_net"]
        demoted = group.loc[group["ml_treatment_group"].eq("demoted_out_of_top_k"), "future_excess_log_return_net"]
        rule_mean = float(rule.mean()) if not rule.empty else np.nan
        hybrid_mean = float(hybrid.mean()) if not hybrid.empty else np.nan
        rows.append({
            "date": date,
            "label_maturity_date": group["label_maturity_date"].max(),
            "rule_top_k_net_alpha": rule_mean,
            "hybrid_top_k_net_alpha": hybrid_mean,
            "ml_incremental_top_k_net_alpha": hybrid_mean - rule_mean,
            "promoted_mean_net_alpha": float(promoted.mean()) if not promoted.empty else np.nan,
            "demoted_mean_net_alpha": float(demoted.mean()) if not demoted.empty else np.nan,
            "promotion_minus_demotion_net_alpha": (
                float(promoted.mean() - demoted.mean())
                if not promoted.empty and not demoted.empty else np.nan
            ),
            "treated_candidate_count": int(len(promoted) + len(demoted)),
        })
    return pd.DataFrame(rows)
