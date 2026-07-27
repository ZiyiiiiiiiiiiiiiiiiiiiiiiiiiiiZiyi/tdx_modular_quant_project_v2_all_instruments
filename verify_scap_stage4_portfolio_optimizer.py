"""Stage-4 checks for bounded one-lot portfolio selection."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.small_capital_aggressive import select_scap_one_lot_portfolio


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> None:
    candidates = pd.DataFrame([
        {"symbol": "A", "scap_candidate_utility": 10.0, "mainline_v3_one_lot_cash_required": 6_000.0},
        {"symbol": "B", "scap_candidate_utility": 9.0, "mainline_v3_one_lot_cash_required": 5_000.0},
        {"symbol": "C", "scap_candidate_utility": 9.0, "mainline_v3_one_lot_cash_required": 5_000.0},
        {"symbol": "NEG", "scap_candidate_utility": -1.0, "mainline_v3_one_lot_cash_required": 1_000.0},
    ])
    selection = select_scap_one_lot_portfolio(
        candidates,
        eligible_mask=pd.Series(True, index=candidates.index),
        available_cash=12_000.0,
        min_cash_buffer=2_000.0,
        remaining_slots=2,
    )
    symbols = set(candidates.loc[list(selection.selected_indices), "symbol"])
    _check(symbols == {"B", "C"}, "optimizer beats greedy selection under one-lot cash constraints")
    _check(abs(selection.residual_cash) < 1e-12, "optimizer preserves the registered cash buffer exactly")
    _check(selection.candidate_pool_size == 3, "negative-utility candidate is not forced into the portfolio")
    one_slot = select_scap_one_lot_portfolio(
        candidates,
        eligible_mask=pd.Series(True, index=candidates.index),
        available_cash=12_000.0,
        min_cash_buffer=2_000.0,
        remaining_slots=1,
    )
    _check(candidates.loc[list(one_slot.selected_indices), "symbol"].tolist() == ["A"], "one-slot experiment selects maximum utility")
    none = select_scap_one_lot_portfolio(
        candidates,
        eligible_mask=pd.Series(True, index=candidates.index),
        available_cash=2_000.0,
        min_cash_buffer=2_000.0,
        remaining_slots=5,
    )
    _check(not none.selected_indices, "zero spendable cash does not force an entry")


if __name__ == "__main__":
    main()
