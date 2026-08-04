from __future__ import annotations

import numpy as np
import pandas as pd

from functions.decision_council.regime_factor_diagnostics import (
    _benjamini_hochberg,
    _daily_metrics,
    summarize_daily_metrics,
)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


rng = np.random.default_rng(17)
rows = []
for day in pd.date_range("2025-01-02", periods=40, freq="B"):
    score = np.arange(30, dtype=float)
    outcome = score / 30.0 + rng.normal(0, 0.08, len(score))
    for index in range(len(score)):
        rows.append({"date": day, "symbol": f"s{index:03d}", "score": score[index], "outcome": outcome[index]})
frame = pd.DataFrame(rows)
daily = _daily_metrics(frame, score_column="score", outcome_column="outcome")
check(len(daily) == 40, "all synthetic dates are evaluated")
check(daily["rank_ic"].mean() > 0.90, "known positive cross-sectional signal produces positive IC")
check(daily["direction_accuracy"].mean() > 0.80, "direction accuracy uses cross-sectional median sides")

decorated = daily.assign(
    score_scope="test_scope", score_level="factor", score_name="known_signal",
    economic_family="test", module="test", horizon_days=5,
    state_dimension="all", state_label="all",
)
summary = summarize_daily_metrics(decorated)
check(len(summary) == 1 and summary.iloc[0]["observed_days"] == 40, "summary preserves observed day count")
check(bool(summary.iloc[0]["fdr_10pct_pass"]), "strong known signal passes BH-FDR")

q_values = _benjamini_hochberg(pd.Series([0.01, 0.04, 0.20]))
check(np.allclose(q_values.to_numpy(), [0.03, 0.06, 0.20]), "Benjamini-Hochberg adjustment is monotone and exact")

shuffled = frame.copy()
shuffled["outcome"] = rng.permutation(shuffled["outcome"].to_numpy())
shuffled_daily = _daily_metrics(shuffled, score_column="score", outcome_column="outcome")
check(abs(shuffled_daily["rank_ic"].mean()) < 0.10, "shuffled negative control destroys IC")
