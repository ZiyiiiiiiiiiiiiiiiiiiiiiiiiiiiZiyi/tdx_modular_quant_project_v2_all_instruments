"""Verify governance excess return is the geometric account/benchmark NAV ratio."""
import pandas as pd

from functions.decision_council.analytics import build_governance_attribution


daily = pd.DataFrame(
    {
        "date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
        "nominal_nav": [100.0, 110.0, 99.0],
        "liquidatable_nav": [100.0, 110.0, 99.0],
        "cash": [0.0, 0.0, 0.0],
        "invested_value": [100.0, 110.0, 99.0],
        "actual_exposure": [1.0, 1.0, 1.0],
    }
)
features = pd.DataFrame(
    {
        "date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
        "symbol": ["000001", "000001", "000001"],
        "close_nominal": [100.0, 105.0, 105.0],
        "amount": [1_000_000.0] * 3,
    }
)
result = build_governance_attribution(
    daily_result=daily,
    feature_data=features,
    benchmark_symbol="000001",
)
account = float(result.iloc[-1]["account_net_value"])
benchmark = float(result.iloc[-1]["benchmark_net_value"])
relative = float(result.iloc[-1]["excess_net_value"])
assert abs(relative - account / benchmark) < 1e-12
assert result["benchmark_relative_return_method"].eq("geometric_nav_ratio").all()
active_chain = float(result.iloc[-1]["active_return_difference_chain_net_value"])
assert abs(active_chain - relative) > 1e-6
print("[PASS] benchmark excess return uses geometric NAV ratio; arithmetic chain is separate")
