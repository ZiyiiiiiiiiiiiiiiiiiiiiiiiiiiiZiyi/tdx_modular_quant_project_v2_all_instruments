"""Stage-6 checks for the small-account research admission gate."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.scap_admission import build_scap_admission_report
from main_launcher_web import _sanitize_selection_payload


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> None:
    dates = pd.bdate_range("2023-01-02", periods=520)
    daily = pd.DataFrame({
        "date": dates,
        "account_net_value": 1.0 + pd.Series(range(len(dates))) * 0.001,
        "structural_regime_level": ["bull", "neutral", "warning", "bull"] * 130,
    })
    summary = pd.DataFrame([{
        "final_net_value": 1.30,
        "total_return": 0.30,
        "profit_factor": 1.30,
        "closed_trade_count": 180,
        "trading_days": 520,
        "closed_trade_win_rate": 0.48,
        "payoff_ratio": 1.50,
    }])
    stress = pd.DataFrame([
        {"minimum_commission": 5.0, "market_cost_multiplier": 1.0, "scenario_profitable": True, "profit_factor_after_cost": 1.20},
        {"minimum_commission": 5.0, "market_cost_multiplier": 2.0, "scenario_profitable": True, "profit_factor_after_cost": 1.05},
    ])
    holdings = pd.DataFrame([{"date": dates[-1], "account_weight": 0.31}])
    report = build_scap_admission_report(
        governance_summary=summary,
        cost_stress=stress,
        daily_result=daily,
        holdings_ledger=holdings,
        initial_cash=20_000.0,
    ).iloc[0]
    _check(report["profit_style_path"] == "right_tail", "payoff path passes without a high win rate")
    _check(bool(report["structural_concentration_pass"]), "31 percent one-lot concentration passes the 40 percent structural cap")
    _check(bool(report["institutional_25pct_gate_is_diagnostic_only"]), "institutional 25 percent gate is diagnostic only")
    _check(bool(report["research_stage_eligible"]), "complete positive evidence enters the next research stage")
    _check(not bool(report["production_eligible"]), "historical evidence cannot bypass prospective paper admission")
    failed = summary.copy()
    failed.loc[0, "profit_factor"] = 0.90
    blocked = build_scap_admission_report(
        governance_summary=failed,
        cost_stress=stress,
        daily_result=daily,
        holdings_ledger=holdings,
        initial_cash=20_000.0,
    ).iloc[0]
    _check(not bool(blocked["research_stage_eligible"]), "PF below one remains blocked despite drawdown tolerance")
    product = _sanitize_selection_payload({
        "tasks": [],
        "governance": {
            "control_mode": "aggressive_profit",
            "strategy_logic_version": "mainline_v3_cabinet_native",
            "scap_exit_stage": "E3",
            "scap_loss_stop": "-0.12",
        },
    })
    _check(product["governance"]["scap_exit_stage"] == "E3", "Web product payload preserves the exit experiment")
    _check(product["governance"]["scap_loss_stop"] == -0.12, "Web product payload normalizes the loss boundary")
    try:
        _sanitize_selection_payload({
            "tasks": [],
            "governance": {
                "control_mode": "aggressive_profit",
                "strategy_logic_version": "production_v1",
            },
        })
    except ValueError:
        print("[PASS] Web product rejects SCAP with a non-v3 strategy")
    else:
        raise AssertionError("Web product accepted SCAP with a non-v3 strategy")


if __name__ == "__main__":
    main()
