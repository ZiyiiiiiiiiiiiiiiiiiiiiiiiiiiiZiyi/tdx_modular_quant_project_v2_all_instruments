"""Product checks for cross-scope funnel rate suppression."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.candidate_funnel_audit import FUNNEL_COUNT_COLUMNS, summarize_funnel


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main():
    row = {column: 100 for column in FUNNEL_COUNT_COLUMNS}
    row.update({"entry_confirmation_pass_count": 60, "state_machine_role_pass_count": 60,
                "risk_pass_count": 60, "reputation_pass_count": 60, "regime_pass_count": 60,
                "cooldown_pass_count": 60, "capital_pass_count": 116,
                "ideal_portfolio_count": 60, "order_count": 3, "executed_buy_count": 3})
    summary = summarize_funnel(pd.DataFrame([row]))
    capital = summary[summary["stage"].eq("capital_pass_count")].iloc[0]
    check(not bool(capital["comparable_to_previous"]), "wider capital scope is marked non-comparable")
    check(pd.isna(capital["pass_rate_from_previous"]), "cross-scope rate is suppressed instead of exceeding one")
    check(pd.isna(capital["rejected_from_previous"]), "cross-scope rejection count is not fabricated")
    rates = pd.to_numeric(summary["pass_rate_from_previous"], errors="coerce").dropna()
    check(rates.le(1.0).all(), "published comparable funnel rates never exceed one")
    orders = summary[summary["stage"].eq("order_count")].iloc[0]
    check(bool(orders["comparable_to_previous"]) and float(orders["pass_rate_from_previous"]) == .05, "subsequent comparable stage keeps its real conversion rate")
    print("[PASS] candidate funnel scope product verification completed")


if __name__ == "__main__":
    main()
