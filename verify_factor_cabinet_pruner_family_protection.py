from __future__ import annotations

import pandas as pd

from functions.decision_council.factor_cabinet_pruner import (
    PROTECTED_ECONOMIC_FAMILY_MIN,
    _economic_family_representatives,
    _rank_candidates,
)


def main() -> int:
    rows = pd.DataFrame(
        [
            {"factor_name": "generic", "role": "timing_filter", "family": "momentum", "score": 9.0},
            {"factor_name": "breakout_best", "role": "timing_filter", "family": "breakout", "score": 0.4},
            {"factor_name": "breakout_second", "role": "timing_filter", "family": "breakout", "score": 0.2},
            {"factor_name": "orderflow_best", "role": "liquidity_filter", "family": "orderflow", "score": 0.3},
            {"factor_name": "orderflow_second", "role": "liquidity_filter", "family": "orderflow", "score": 0.1},
        ]
    )
    rows["best_ic_ir"] = 0.0
    rows["best_cost_adjusted_top_bottom_spread"] = 0.0
    rows["strict_entry_alpha"] = False
    ranked = _rank_candidates(rows)
    protected = _economic_family_representatives(ranked)
    assert PROTECTED_ECONOMIC_FAMILY_MIN == {"orderflow": 1, "breakout": 1}
    assert protected == {"breakout_best", "orderflow_best"}
    print("[PASS] pruner protects the strongest bounded orderflow and breakout representatives")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
