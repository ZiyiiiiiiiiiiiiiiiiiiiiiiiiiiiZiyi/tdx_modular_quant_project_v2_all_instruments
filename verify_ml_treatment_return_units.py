"""Verify ML trading authority is measured in net-return, not rank, units."""
import numpy as np
import pandas as pd

from functions.decision_council.monthly_lgbm_hybrid import (
    _hac_standard_error,
    _validation_top_k_treatment,
)


def main():
    rows = []
    for date_index, date in enumerate(pd.bdate_range("2024-01-02", periods=24)):
        for symbol_index in range(10):
            rule = float(symbol_index)
            ml = float(9 - symbol_index)
            # ML-selected low symbol indices earn a stable two-percent net
            # alpha; rule-selected high indices earn zero.
            net = 0.02 if symbol_index < 5 else 0.0
            rows.append({
                "date": date,
                "rule_rank": rule / 9.0,
                "ml_rank": ml / 9.0,
                "realized_net_alpha": net,
                "realized_rank": 1.0 if net > 0 else 0.5,
            })
    data = pd.DataFrame(rows)
    effect = _validation_top_k_treatment(data, weight=1.0, top_k=5)
    assert np.allclose(effect, 0.02), effect.tolist()
    print("[PASS] Top-K treatment effect remains in cost-after return units")

    se5 = _hac_standard_error(effect, max_lag=4)
    se20 = _hac_standard_error(effect, max_lag=19)
    assert np.isfinite(se5) and np.isfinite(se20)
    print("[PASS] HAC supports horizon-derived 5-day and 20-day overlap lags")


if __name__ == "__main__":
    main()
