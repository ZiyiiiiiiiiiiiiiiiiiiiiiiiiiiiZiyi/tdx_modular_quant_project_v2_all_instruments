import numpy as np
import pandas as pd

from functions.decision_council.full_universe_factor_oos import _cross_sectional_ic_rows, build_rolling_conditional_selection


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


rows = []
for date in pd.date_range("2024-01-02", periods=190, freq="B"):
    for index in range(40):
        rows.append({"date": date, "symbol": f"s{index}", "good": index, "bad": -index, "forward_return_5d": index / 40})
ic = pd.DataFrame(_cross_sectional_ic_rows(pd.DataFrame(rows), ["good", "bad"], 5))
check(ic.groupby("raw_column")["rank_ic"].mean()["good"] > 0.99, "full-universe known signal has positive IC")
check(ic.groupby("raw_column")["rank_ic"].mean()["bad"] < -0.99, "inverse signal has negative IC")

daily = []
for date in pd.date_range("2024-01-02", periods=190, freq="B"):
    daily.extend([
        {"date": date, "horizon_days": 5, "safety_structural_state": "neutral", "economic_family": "test", "score_name": "good", "rank_ic": 0.1, "sample_count": 40},
        {"date": date, "horizon_days": 5, "safety_structural_state": "neutral", "economic_family": "test", "score_name": "bad", "rank_ic": -0.1, "sample_count": 40},
    ])
selection, evaluation = build_rolling_conditional_selection(pd.DataFrame(daily))
check(not selection.empty, "rolling selector starts only after the required history")
check(selection["selected_factor"].eq("good").all(), "rolling selector uses prior IC only")
check((pd.to_datetime(selection["train_end"]) < pd.PeriodIndex(selection["test_month"], freq="M").to_timestamp()).all(), "training ends before every test month")
check(not evaluation.empty, "rolling test evaluation is emitted")
