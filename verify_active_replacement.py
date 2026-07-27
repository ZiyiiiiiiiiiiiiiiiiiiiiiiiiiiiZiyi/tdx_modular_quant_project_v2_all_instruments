from __future__ import annotations

import pandas as pd

from functions.decision_council.active_replacement import choose_active_replacements
from functions.decision_council.multi_horizon_value import attach_multi_horizon_value_contract


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> int:
    source = pd.DataFrame([
        {"symbol": "held", "expected_edge_10d": 0.002, "conservative_expected_edge_10d": -0.003, "strategy_logic_version": "mainline_v3_cabinet_native",
         "entry_confirmed": False, "state_machine_role_pass": True, "mainline_v3_lot_feasible": True},
        {"symbol": "better", "expected_edge_10d": 0.030, "conservative_expected_edge_10d": 0.020, "strategy_logic_version": "mainline_v3_cabinet_native",
         "entry_confirmed": True, "state_machine_role_pass": True, "mainline_v3_lot_feasible": True},
        {"symbol": "rank_only", "entry_matrix_score": 1.0, "strategy_logic_version": "mainline_v3_cabinet_native",
         "entry_confirmed": True, "state_machine_role_pass": True, "mainline_v3_lot_feasible": True},
    ])
    data = attach_multi_horizon_value_contract(source)
    pairs = choose_active_replacements(
        data,
        current_weights={"held": 0.25},
        holding_days={"held": 10},
        decision_date="2024-01-10",
        minimum_holding_days=5,
    )
    expect(len(pairs) == 1 and pairs[0].challenger_symbol == "better",
           "a bounded cost-after-return challenger actively replaces an eligible holding")
    expect(pairs[0].lcb_net_edge > 0.0 and pairs[0].lcb_net_edge < pairs[0].expected_net_edge,
           "replacement authorization uses the conservative net advantage")
    blocked = choose_active_replacements(
        data,
        current_weights={"held": 0.25},
        holding_days={"held": 2},
        decision_date="2024-01-10",
        minimum_holding_days=5,
    )
    expect(not blocked, "minimum holding constraint prevents premature churn")
    expect(all(pair.challenger_symbol != "rank_only" for pair in pairs),
           "rank percentiles cannot authorize a cost-after-return replacement")
    # A challenger rejected by the unified position state cannot authorize the
    # sell leg; otherwise execution can liquidate without registering its buy.
    blocked_state = data.copy()
    blocked_state.loc[
        blocked_state["symbol"].eq("better"), "position_state"
    ] = "blocked"
    assert choose_active_replacements(
        blocked_state,
        current_weights={"held": 0.25},
        holding_days={"held": 10},
        decision_date="2024-01-10",
        minimum_holding_days=5,
    ) == []
    print("[PASS] a blocked challenger cannot create an orphan replacement sell")
    print("[PASS] active replacement verification completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
