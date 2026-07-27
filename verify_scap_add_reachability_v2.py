"""SCAP winner/loser add reachability with utility and exit precedence."""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from functions.decision_council.execution_runtime import Position
from functions.decision_council.position_lifecycle import apply_position_state_constraints


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


class Runner:
    def __init__(self):
        self.positions = {
            "winner": Position(100.0, pd.Timestamp("2025-01-02")),
            "loser": Position(100.0, pd.Timestamp("2025-01-02")),
        }
        self.holding_days = {"winner": 10, "loser": 10}
        self.position_lifecycle = {
            "winner": {"buy_count": 1, "entry_module_support": 0.5, "entry_thesis": "composite"},
            "loser": {"buy_count": 1, "entry_module_support": 0.5, "entry_thesis": "composite"},
        }
        self.position_cooldowns = {}
        self.position_exit_confirmations = {}
        self.position_state_rows = []
        self._last_position_mark_rows = [
            {"symbol": "winner", "market_value": 1_100.0},
            {"symbol": "loser", "market_value": 900.0},
        ]
        self.capital_profile = {
            "scap_loser_averaging_enabled": True,
            "scap_winner_pyramiding_enabled": True,
            "scap_winner_pyramiding_trigger_returns": (0.05, 0.10),
            "retail_single_position_cap": 0.40,
            "scap_signal_failure_confirmation_days": 3,
            "scap_cooldown_override_enabled": False,
            "scap_loss_stop": -0.12,
        }
        self.governance_control_mode = "aggressive_profit"
        self.strategy_logic_version = "mainline_v3_cabinet_native"

    def _expire_position_cooldowns(self, date):
        return None

    def _max_add_layers(self):
        return 3

    def _control_enabled(self, name):
        return True


def main():
    runner = Runner()
    common = {
        "entry_matrix_score": 0.50,
        "alpha_quality_score": 0.50,
        "cabinet_hold_support_score": 0.50,
        "trend_hold_score": 0.50,
        "entry_success_probability": 0.50,
        "final_entry_score": 0.50,
        "trend_stability_score": 0.50,
        "volume_health_score": 0.50,
        "trend_direction_score": 0.60,
        "downtrend_decay_score": 0.20,
        "post_entry_failure_score": 0.10,
        "exhaustion_score": 0.20,
        "tail_risk_proxy": 0.10,
        "close_nominal": 10.0,
        "mainline_v3_one_lot_cash_required": 1_005.0,
        "comparable_expected_alpha": 0.05,
        "comparable_alpha_lcb": 0.03,
        "comparable_value_horizon_days": 10,
        "position_mfe": 0.06,
        "position_mae": -0.03,
        "position_giveback_from_peak": 0.0,
        "profit_giveback_exit": False,
        "post_entry_failure_watch": False,
    }
    data = pd.DataFrame(
        [
            {**common, "symbol": "winner", "position_unrealized_return": 0.06},
            {**common, "symbol": "loser", "position_unrealized_return": -0.04},
        ]
    )
    result = apply_position_state_constraints(
        runner,
        data,
        date=pd.Timestamp("2025-01-20"),
        exposure={"nominal_nav": 20_000.0},
    ).set_index("symbol")
    check(bool(result.loc["winner", "add_allowed"]), "winner pyramiding is mathematically reachable")
    check(result.loc["winner", "add_decision_type"] == "winner_pyramiding", "winner add has an independent decision type")
    check(bool(result.loc["loser", "add_allowed"]), "loser averaging is mathematically reachable")
    check(result.loc["loser", "add_decision_type"] == "loser_averaging", "loser add has an independent decision type")
    check((result["add_expected_net_profit_lcb"] > 0.0).all(), "both add paths require positive yuan LCB")

    exit_data = data.iloc[[1]].copy()
    exit_data["position_unrealized_return"] = -0.20
    blocked = apply_position_state_constraints(
        runner,
        exit_data,
        date=pd.Timestamp("2025-01-21"),
        exposure={"nominal_nav": 20_000.0},
    ).iloc[0]
    check(not bool(blocked["add_allowed"]), "authorized exit vetoes loser averaging")
    check(str(blocked["unified_action_selected"]) == "exit", "exit remains the single selected direction")


if __name__ == "__main__":
    main()
