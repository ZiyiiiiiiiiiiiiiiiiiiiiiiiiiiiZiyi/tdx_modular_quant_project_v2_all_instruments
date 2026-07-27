from __future__ import annotations

import pandas as pd

from functions.decision_council.action_counterfactual_reward import build_action_decisions, mature_action_rewards


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> int:
    candidate_rows = pd.DataFrame([
        {"symbol": "held", "comparable_value_horizon_days": 10, "comparable_alpha_lcb": 0.001,
         "entry_confirmed": False, "mainline_v3_lot_feasible": True},
        {"symbol": "better", "comparable_value_horizon_days": 10, "comparable_alpha_lcb": 0.010,
         "entry_confirmed": True, "mainline_v3_lot_feasible": True},
    ])
    decision_rows = build_action_decisions(
        date="2024-01-02", candidates=candidate_rows, held_symbols={"held"}, orders=pd.DataFrame(),
        daily=pd.DataFrame([{"symbol": "held", "close": 10.0}, {"symbol": "better", "close": 11.0}]),
    )
    expect(decision_rows and decision_rows[0]["alternative_symbol"] == "better",
           "holding reward selects a comparable challenger without symbol index ambiguity")
    dates = pd.bdate_range("2024-01-02", periods=22)
    rows = []
    for i, date in enumerate(dates):
        rows.extend([
            {"date": date, "symbol": "held", "close": 100.0 * (1.0 + 0.001 * i)},
            {"date": date, "symbol": "better", "close": 100.0 * (1.0 + 0.003 * i)},
            {"date": date, "symbol": "benchmark", "close": 100.0 * (1.0 + 0.0005 * i)},
        ])
    decisions = pd.DataFrame([
        {"decision_id": "r5", "decision_date": dates[0], "symbol": "held", "action": "replace", "reason": "test",
         "horizon_days": 5, "symbol_price": 100.0, "alternative_symbol": "better", "alternative_price": 100.0,
         "estimated_action_cost_rate": 0.002, "maturity_status": "pending"},
        {"decision_id": "s5", "decision_date": dates[0], "symbol": "held", "action": "sell", "reason": "test",
         "horizon_days": 5, "symbol_price": 100.0, "alternative_symbol": "", "alternative_price": pd.NA,
         "estimated_action_cost_rate": 0.001, "maturity_status": "pending"},
        {"decision_id": "c20", "decision_date": dates[5], "symbol": "held", "action": "hold", "reason": "test",
         "horizon_days": 20, "symbol_price": 100.5, "alternative_symbol": "better", "alternative_price": 101.5,
         "estimated_action_cost_rate": 0.002, "maturity_status": "pending"},
    ])
    out = mature_action_rewards(decisions, pd.DataFrame(rows), benchmark_symbol="benchmark").set_index("decision_id")
    expect(out.at["r5", "maturity_status"] == "matured" and float(out.at["r5", "action_reward"]) > 0.0,
           "a superior replacement earns a positive cost-after-market reward")
    expect(float(out.at["s5", "action_reward"]) < 0.0,
           "selling a stock that subsequently has positive market-neutral return is penalized")
    expect(out.at["c20", "maturity_status"] == "censored",
           "an incomplete horizon is censored rather than scored with partial future data")
    unfilled = mature_action_rewards(
        decisions.iloc[[1]], pd.DataFrame(rows), benchmark_symbol="benchmark",
        executions=pd.DataFrame(columns=["signal_date", "trade_date", "symbol", "side", "executed_shares"]),
    ).iloc[0]
    expect(unfilled["planned_action"] == "sell" and unfilled["actual_action"] == "hold",
           "an unfilled planned sell is scored as the actual hold action")
    executions = pd.DataFrame([
        {"signal_date": dates[0], "trade_date": dates[1], "symbol": "held", "side": "sell",
         "executed_shares": 100, "execution_status": "filled", "price": 100.1,
         "trade_notional": 10010.0, "total_cost": 10.01, "replacement_pair_id": "p1"},
        {"signal_date": dates[0], "trade_date": dates[2], "symbol": "better", "side": "buy",
         "executed_shares": 100, "execution_status": "filled", "price": 100.6,
         "trade_notional": 10060.0, "total_cost": 5.03, "replacement_pair_id": "p1"},
    ])
    filled = mature_action_rewards(
        decisions.iloc[[0]], pd.DataFrame(rows), benchmark_symbol="benchmark", executions=executions,
    ).iloc[0]
    expect(pd.Timestamp(filled["reward_start_date"]) == dates[1],
           "filled replacement reward starts the disposed holding at its sell fill")
    expect(pd.Timestamp(filled["alternative_reward_start_date"]) == dates[2],
           "filled replacement reward starts the challenger at its buy fill")
    expect(abs(float(filled["actual_action_cost_rate"]) - 0.0015) < 1e-12,
           "filled replacement reward uses reconciled sell and buy ledger costs")
    expect(filled["reward_formula_version"] == "market_neutral_actual_fill_cost_counterfactual_v3",
           "reward output discloses the actual-fill formula contract")
    print("[PASS] action counterfactual reward verification completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
