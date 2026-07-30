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

fixed = get_backtest_capital_profile("small_capital_lean")
assert fixed["position_cap_mode"] == "fixed"
assert fixed["max_positions"] == 5

auto = get_backtest_capital_profile(
    "small_capital_lean",
    max_positions_override=0,
)
assert auto["position_cap_mode"] == "auto"
assert auto["max_positions"] is None

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
fixed_authority = attach_scap_v31_authority(authority_input)
auto_authority = attach_scap_v31_authority(
    authority_input,
    position_cap_mode="auto",
    target_position_cash=20_000.0,
)
assert int(fixed_authority.iloc[0]["scap_v31_max_lots"]) == 2
assert int(auto_authority.iloc[0]["scap_v31_max_lots"]) == 20

launcher = (root / "main_launcher_web.py").read_text(encoding="utf-8")
assert 'id="initial_cash" min="1" step="1000" value=""' in launcher
assert 'id="max_positions_account" min="0" step="1" value=""' in launcher
assert "0=资金/整手/成本自动上限" in launcher
assert "不是永久产品定义" in launcher

print("[PASS] capital-scaled fixed/auto position identity and launcher contract")
