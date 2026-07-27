"""Verify SCAP evidence gates are compatible with a 20-day, five-slot design."""
import numpy as np
import pandas as pd

from functions.decision_council.scap_admission import build_scap_admission_report


days = 504
daily = pd.DataFrame(
    {
        "date": pd.bdate_range("2023-01-02", periods=days),
        "account_net_value": np.linspace(1.0, 1.30, days),
        "structural_regime_level": (
            ["bull"] * 168 + ["weak"] * 168 + ["bear"] * 168
        ),
    }
)
summary = pd.DataFrame(
    [
        {
            "final_net_value": 1.30,
            "total_return": 0.30,
            "profit_factor": 1.3,
            "closed_trade_count": 30,
            "trading_days": days,
            "closed_trade_win_rate": 0.60,
            "payoff_ratio": 1.4,
        }
    ]
)
stress = pd.DataFrame(
    [
        {
            "minimum_commission": 5.0,
            "market_cost_multiplier": 1.0,
            "scenario_profitable": True,
            "profit_factor_after_cost": 1.2,
        },
        {
            "minimum_commission": 5.0,
            "market_cost_multiplier": 2.0,
            "scenario_profitable": True,
            "profit_factor_after_cost": 1.1,
        },
    ]
)
report = build_scap_admission_report(
    governance_summary=summary,
    cost_stress=stress,
    daily_result=daily,
    holdings_ledger=pd.DataFrame(),
    initial_cash=20_000.0,
).iloc[0]
assert report["opportunity_capacity_20d_5_slots"] == 126
assert report["required_closed_trade_evidence"] == 30
assert report["rolling_slice_count"] >= 4
assert report["closed_trade_evidence_pass"]
assert report["positive_slice_share_pass"]
print("[PASS] SCAP admission is opportunity- and rolling-slice compatible")
