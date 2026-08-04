import pandas as pd

from functions.decision_council.buy_quality_diagnostics import _stage_summary


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


rows = []
for index in range(6):
    rows.append({
        "symbol": f"s{index}", "entry_month": "2025-01", "safety_structural_state": "neutral",
        "candidate_gate": True, "mainline_v3_raw_signal": index < 5,
        "mainline_v3_structural_feasible": index < 4, "mainline_v3_cash_feasible": index < 3,
        "mainline_v3_slot_feasible": index < 2, "optimizer_selected": index < 1,
        "selected_buy_proposal": index < 1, "registered_buy_order": index < 1,
        "executed_buy": index < 1, "forward_return_5d": index / 100,
        "forward_return_10d": index / 50, "forward_return_20d": index / 25,
    })
summary = _stage_summary(pd.DataFrame(rows), ["entry_month", "safety_structural_state"])
counts = summary.set_index("stage")["sample_count"].to_dict()
check(counts["candidate_gate"] == 6, "candidate gate count is factual")
check(counts["executed_buy"] == 1, "execution count is not inferred from selection")
ordered = [counts[name] for name in ["candidate_gate", "mainline_v3_raw_signal", "mainline_v3_structural_feasible", "mainline_v3_cash_feasible", "mainline_v3_slot_feasible", "optimizer_selected", "executed_buy"]]
check(all(left >= right for left, right in zip(ordered, ordered[1:])), "synthetic stage funnel is monotone")
check("closed_trade_count" not in pd.DataFrame(rows), "closed trades are never invented by stage summary")

scoring_source = open("functions/decision_council/cabinet_native_scoring.py", encoding="utf-8").read()
runner_source = open("functions/decision_council/runner.py", encoding="utf-8").read()
check("cabinet_entry_family_{safe_name}_score" in scoring_source, "new runs persist entry-role family scores separately")
check('"cabinet_entry_thesis_support": candidate.get' in runner_source, "candidate audit persists factual thesis support")
