from pathlib import Path

import pandas as pd

from functions.decision_council.candidate_pool_contract import (
    select_feasible_candidate_pool,
)


rows = []
for index in range(12):
    rows.append(
        {
            "symbol": f"sh688{index:03d}",
            "scap_candidate_utility": 1000.0 - index,
            "mainline_v3_one_lot_cash_required": 6500.0,
            "scap_v31_max_lots": 1,
            "scap_v31_authority_tier": "C",
            "mainline_v3_market_permission_feasible": False,
            "mainline_v3_lot_feasible": False,
            "mainline_v3_structural_feasible": False,
            "mainline_v3_cash_feasible": True,
            "lifecycle_held_row": False,
            "exit_state": False,
            "position_state": "flat",
            "cabinet_entry_thesis": "size_style",
            "primary_score": 0.99,
        }
    )
for index, thesis in enumerate(("value", "growth", "momentum", "reversal") * 3):
    rows.append(
        {
            "symbol": f"sz00{index:04d}",
            "scap_candidate_utility": 20.0 - index * 0.2,
            "mainline_v3_one_lot_cash_required": 1800.0 + index * 10.0,
            "scap_v31_max_lots": 1,
            "scap_v31_authority_tier": "C",
            "mainline_v3_market_permission_feasible": True,
            "mainline_v3_lot_feasible": True,
            "mainline_v3_structural_feasible": True,
            "mainline_v3_cash_feasible": True,
            "lifecycle_held_row": False,
            "exit_state": False,
            "position_state": "flat",
            "cabinet_entry_thesis": thesis,
            "primary_score": 0.70 - index * 0.01,
        }
    )
frame = pd.DataFrame(rows)
selected, factual, positive = select_feasible_candidate_pool(
    frame,
    limit=8,
    per_pool_reserve=1,
)
chosen = frame.loc[selected]
assert len(chosen) == 8
assert chosen["mainline_v3_lot_feasible"].all()
assert not chosen["symbol"].str.startswith("sh688").any()
assert chosen["cabinet_entry_thesis"].nunique() == 4
assert int(factual.sum()) == 12
assert int(positive.sum()) == 12
print("[PASS] infeasible high-CNY lots cannot crowd out the feasible pool")
print("[PASS] pool reservation occurs before global computational truncation")

review = frame.iloc[[12]].copy()
review["symbol"] = "sz009999"
review["scap_candidate_utility"] = -4.0
review["scap_v31_max_lots"] = 3
review["scap_v31_decision_expected_return"] = 0.025
review_selected, _, _ = select_feasible_candidate_pool(
    review,
    limit=1,
    per_pool_reserve=1,
)
assert review_selected
print("[PASS] fixed-commission multi-lot rescue reaches exact-cost review")

lean_source = Path("functions/decision_council/scap_v3_lean.py").read_text(
    encoding="utf-8"
)
assert "def _entry_shortlist_symbols" not in lean_source
assert '"scap_action_candidate" in data.columns' in lean_source
print("[PASS] Lean has no independent production shortlist formula")

runner_source = Path("functions/decision_council/runner.py").read_text(
    encoding="utf-8"
)
for field in (
    "scap_action_candidate",
    "scap_candidate_pool_factual_feasible",
    "scap_candidate_pool_positive_feasible",
    "scap_candidate_pool_contract_version",
):
    assert field in runner_source
print("[PASS] authoritative candidate state survives the saved audit interface")
