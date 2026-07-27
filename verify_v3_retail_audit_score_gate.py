from __future__ import annotations

from functions.decision_council.runner import _retail_entry_score_gate_pass


def main() -> None:
    low_raw_score = {"entry_matrix_score": 0.41}
    assert _retail_entry_score_gate_pass(
        low_raw_score,
        strategy_logic_version="mainline_v3_cabinet_native",
        minimum_score=0.60,
    )
    assert _retail_entry_score_gate_pass(
        low_raw_score,
        strategy_logic_version="mainline_v3_monthly_lgbm_hybrid",
        minimum_score=0.60,
    )
    assert not _retail_entry_score_gate_pass(
        low_raw_score,
        strategy_logic_version="mainline_v2",
        minimum_score=0.60,
    )
    print("[PASS] v3 retail audit does not reapply the legacy matrix-score gate")


if __name__ == "__main__":
    main()
