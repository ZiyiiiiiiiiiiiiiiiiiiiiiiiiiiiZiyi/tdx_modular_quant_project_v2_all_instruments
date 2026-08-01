"""Verify authority, loser-add and post-plan permissions fail closed."""
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from functions.decision_council.scap_v31_authority import (
    attach_scap_v31_authority,
)
from functions.decision_council.scap_v3_lean import _append_held_proposals


missing = pd.DataFrame(
    {
        "symbol": ["600001"],
        "close_nominal": [10.0],
        "scap_decision_expected_return": [0.05],
        "scap_candidate_utility": [100.0],
    }
)
failed_closed = attach_scap_v31_authority(missing)
assert failed_closed.iloc[0]["scap_v31_authority_tier"] == "D"
assert int(failed_closed.iloc[0]["scap_v31_max_lots"]) == 0
assert "fail_closed_missing_evidence" in failed_closed.iloc[0]["scap_v31_authority_contract"]

context = SimpleNamespace(
    decision_id="d",
    decision_date=pd.Timestamp("2025-01-10"),
    forecast_horizon_sessions=20,
    current_weights={"600001": 0.20},
    nav_amount=20_000.0,
    cash_amount=10_000.0,
    cash_buffer_amount=1_000.0,
    per_name_structural_cap=0.40,
    winner_add_enabled=False,
    loser_add_enabled=True,
    execution_cost_profile={"scap_max_winner_add_layers": 0},
)
row = pd.Series(
    {
        "exit_state": False,
        "position_unrealized_return": -0.06,
        "add_layer": 2,
        "add_expected_net_profit_lcb": 30.0,
        "scap_estimated_total_cost_amount": 10.0,
        "scap_v32_current_authority_tier": "B",
        "scap_authority_snapshot_id": "d|authority",
        "add_allowed": False,
        "add_decision_type": "loser_averaging",
        "loser_averaging": False,
    }
)
proposals = []
rows = {}
_append_held_proposals(
    proposals,
    rows,
    context=context,
    symbol="600001",
    row=row,
    old_weight=0.20,
    lot_cash=4_010.0,
    lot_market_notional=4_000.0,
    lot_weight=0.20,
)
assert not proposals

allowed = row.copy()
allowed["add_allowed"] = True
allowed["loser_averaging"] = True
_append_held_proposals(
    proposals,
    rows,
    context=context,
    symbol="600001",
    row=allowed,
    old_weight=0.20,
    lot_cash=4_010.0,
    lot_market_notional=4_000.0,
    lot_weight=0.20,
)
assert len(proposals) == 1 and proposals[0].action_type == "loser_add"

runner_source = Path("functions/decision_council/runner.py").read_text(encoding="utf-8")
assert 'self.governance_control_mode != "aggressive_lean"' in runner_source
assert 'post_action_plan_order_augmentation"] = "disabled_unique_action_plan"' in runner_source
print("[PASS] missing authority, loser add and Lean post-plan augmentation fail closed")
