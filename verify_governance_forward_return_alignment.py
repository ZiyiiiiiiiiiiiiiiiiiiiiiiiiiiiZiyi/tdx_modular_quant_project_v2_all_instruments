"""Verify candidate audit outcomes start after the decision date."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.runner import GovernanceBacktestRunner


def main() -> int:
    runner = GovernanceBacktestRunner.__new__(GovernanceBacktestRunner)
    runner._return_pivot = pd.DataFrame(
        {"test": [1.0, 0.10, 0.20, -0.50]},
        index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]),
    )
    observed = runner._forward_return("test", "2024-01-02", 2)
    expected = (1.10 * 1.20) - 1.0
    assert abs(float(observed) - expected) < 1e-12, (observed, expected)
    assert pd.isna(runner._forward_return("test", "2024-01-04", 2))
    assert pd.isna(runner._forward_return("test", "2024-01-02", 0))
    print("[PASS] signal-day return is excluded from forward outcomes")
    print("[PASS] exactly N post-signal observed returns are required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
