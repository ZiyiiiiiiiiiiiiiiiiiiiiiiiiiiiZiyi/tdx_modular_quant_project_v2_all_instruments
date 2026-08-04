"""Capital-scaled position capacity and launcher contract."""
from pathlib import Path

import pandas as pd

from config import get_backtest_capital_profile
from functions.decision_council.capital_scaling import (
    resolve_position_capacity,
    scaled_candidate_budgets,
    scaled_position_weight_caps,
)
from functions.decision_council.scap_v31_authority import attach_scap_v31_authority


root = Path(__file__).resolve().parent

default_auto = get_backtest_capital_profile("small_capital_lean")
assert default_auto["position_cap_mode"] == "auto"
assert default_auto["max_positions"] is None
assert default_auto["user_hard_position_cap"] is None

auto = get_backtest_capital_profile(
    "small_capital_lean",
    max_positions_override=0,
)
assert auto["position_cap_mode"] == "auto"
assert auto["max_positions"] is None
web_capped = get_backtest_capital_profile(
    "small_capital_lean",
    max_positions_override=7,
)
assert web_capped["position_cap_mode"] == "auto"
assert web_capped["max_positions"] is None
assert web_capped["user_hard_position_cap"] == 7

candidates = pd.DataFrame(
    {"mainline_v3_one_lot_cash_required": [1000.0] * 30}
)
small = resolve_position_capacity(
    capital_profile=auto,
    nav_amount=20_000.0,
    cash_amount=20_000.0,
    risk_exposure_ceiling=0.85,
    candidates=candidates,
)
large = resolve_position_capacity(
    capital_profile={
        **auto,
        "scap_search_position_cap": 40,
    },
    nav_amount=100_000.0,
    cash_amount=100_000.0,
    risk_exposure_ceiling=0.85,
    candidates=candidates,
)
assert small.mode == "auto"
assert small.effective_position_cap >= 1
assert large.effective_position_cap >= small.effective_position_cap
assert large.effective_position_cap <= large.search_cap
assert 2_870.0 < small.minimum_economic_order_amount < 2_880.0

capped = resolve_position_capacity(
    capital_profile=web_capped,
    nav_amount=100_000.0,
    cash_amount=100_000.0,
    risk_exposure_ceiling=0.85,
    candidates=candidates,
)
assert capped.effective_position_cap == 7

evidence_ranked = resolve_position_capacity(
    capital_profile=auto,
    nav_amount=20_000.0,
    cash_amount=20_000.0,
    risk_exposure_ceiling=0.85,
    candidates=pd.DataFrame(
        {
            "mainline_v3_one_lot_cash_required": [8_000.0, 1_000.0, 1_000.0, 1_000.0, 1_000.0],
            "primary_score": [1.0, 0.9, 0.8, 0.7, 0.6],
        }
    ),
)
assert evidence_ranked.effective_position_cap == 5

expensive_ranked_first = resolve_position_capacity(
    capital_profile=auto,
    nav_amount=20_000.0,
    cash_amount=20_000.0,
    risk_exposure_ceiling=0.85,
    candidates=pd.DataFrame(
        {
            "symbol": [f"S{i}" for i in range(10)],
            "mainline_v3_one_lot_cash_required": [4_000.0] * 4 + [2_000.0] * 6,
            "primary_score": [1.0 - i * 0.01 for i in range(10)],
        }
    ),
)
assert expensive_ranked_first.effective_position_cap == 7

legacy_hard_notional = resolve_position_capacity(
    capital_profile={
        **auto,
        "scap_minimum_economic_notional_hard_gate_enabled": True,
    },
    nav_amount=20_000.0,
    cash_amount=20_000.0,
    risk_exposure_ceiling=0.85,
    candidates=pd.DataFrame(
        {
            "mainline_v3_one_lot_cash_required": [8_000.0, 1_000.0, 1_000.0, 1_000.0, 1_000.0],
            "primary_score": [1.0, 0.9, 0.8, 0.7, 0.6],
        }
    ),
)
assert legacy_hard_notional.effective_position_cap == 4

risk_room_limited = resolve_position_capacity(
    capital_profile=auto,
    nav_amount=20_000.0,
    cash_amount=10_000.0,
    risk_exposure_ceiling=0.85,
    current_exposure=0.70,
    candidates=candidates,
)
assert risk_room_limited.capacity_risk_room_amount == 3_000.0
assert risk_room_limited.effective_position_cap == 3

held_without_cash = resolve_position_capacity(
    capital_profile=auto,
    nav_amount=20_000.0,
    cash_amount=500.0,
    risk_exposure_ceiling=0.85,
    candidates=pd.DataFrame(
        {
            "symbol": ["held", "new"],
            "mainline_v3_one_lot_cash_required": [1000.0, 1000.0],
        }
    ),
    current_symbols={"held"},
)
assert held_without_cash.effective_position_cap >= 1

soft5, hard5 = scaled_position_weight_caps(
    target_exposure=0.85,
    effective_position_cap=5,
    absolute_soft_cap=0.25,
    absolute_hard_cap=0.40,
)
soft20, hard20 = scaled_position_weight_caps(
    target_exposure=0.85,
    effective_position_cap=20,
    absolute_soft_cap=0.25,
    absolute_hard_cap=0.40,
)
assert 0.24 <= soft5 <= 0.25
assert 0.38 <= hard5 <= 0.40
assert soft20 < soft5
assert hard20 < hard5

budget5 = scaled_candidate_budgets(effective_position_cap=5, pool_count=3)
budget20 = scaled_candidate_budgets(effective_position_cap=20, pool_count=5)
assert budget20["optimizer_candidate_limit"] > budget5["optimizer_candidate_limit"]
assert budget20["thesis_hard_max_names"] > budget5["thesis_hard_max_names"]

authority_input = pd.DataFrame(
    {
        "symbol": ["x"],
        "close_nominal": [10.0],
        "scap_decision_expected_return": [0.02],
    }
)
fixed_authority = attach_scap_v31_authority(
    authority_input,
    allow_synthetic_compatibility=True,
)
auto_authority = attach_scap_v31_authority(
    authority_input,
    position_cap_mode="auto",
    target_position_cash=20_000.0,
    allow_synthetic_compatibility=True,
)
assert int(fixed_authority.iloc[0]["scap_v31_max_lots"]) == 2
assert int(auto_authority.iloc[0]["scap_v31_max_lots"]) == 20

grandfathered = resolve_position_capacity(
    capital_profile=auto,
    nav_amount=20_000.0,
    cash_amount=500.0,
    risk_exposure_ceiling=0.90,
    candidates=candidates,
    current_symbols={f"held_{index}" for index in range(13)},
    current_exposure=0.85,
)
assert grandfathered.effective_position_cap >= 13
assert grandfathered.sizing_reference_positions == 5
assert grandfathered.sizing_reference_positions < grandfathered.effective_position_cap

launcher = (root / "main_launcher_web.py").read_text(encoding="utf-8")
assert 'id="initial_cash" min="1" step="1000" value=""' in launcher
assert 'id="max_positions_account" min="0" step="1" value=""' in launcher
assert "Web治理硬持仓上限（不是目标持仓数）" in launcher
assert "留空或0=不加用户上限" in launcher
assert "不是永久产品定义" in launcher

print("[PASS] Web hard ceiling, dynamic economic capacity, risk room and launcher contract")
