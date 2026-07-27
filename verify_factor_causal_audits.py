"""Bounded product verification for causal-method routing and estimators."""
from __future__ import annotations

import numpy as np
import pandas as pd

from functions.causal.causal_design_registry import CausalDesignSpec, validate_causal_design
from functions.causal.did_audit import build_did_audit
from functions.causal.dml_audit import build_dml_audit
from functions.causal.negative_control_audit import build_negative_control_audit
from functions.causal.rdd_audit import build_rdd_audit
from functions.causal.scm_audit import build_scm_audit


def main() -> None:
    invalid = validate_causal_design(CausalDesignSpec(
        "rsi_did", "rsi", "RSI above 30", "forward return", "stock", "did", "parallel trends", "signal date"
    ))
    assert not invalid["design_valid"]
    valid = validate_causal_design(CausalDesignSpec(
        "buyback_did", "event", "first buyback announcement", "forward return", "stock", "did", "parallel trends", "announcement timestamp"
    ))
    assert valid["design_valid"]
    print("[PASS] causal registry blocks mechanical DID on technical predictors")

    rng = np.random.default_rng(7)
    rows = []
    dates = pd.bdate_range("2023-01-02", periods=12)
    for unit in range(20):
        treated = unit < 10
        for t, date in enumerate(dates):
            rows.append({"unit": unit, "date": date, "treated": treated, "post": t >= 6,
                         "y": .02 * t + (1.0 if treated and t >= 6 else 0.0) + rng.normal(0, .05)})
    did = build_did_audit(pd.DataFrame(rows), unit_column="unit", date_column="date", outcome_column="y", treated_column="treated", post_column="post")
    assert did.iloc[0]["evidence_status"] == "did_design_pass"
    assert did.iloc[0]["did_effect"] > .8
    print("[PASS] DID recovers a known treatment effect and checks pre-trends")

    scm_rows = []
    for t, date in enumerate(pd.bdate_range("2023-01-02", periods=20)):
        donor_a, donor_b = t * .1, np.sin(t / 4)
        treated = .6 * donor_a + .4 * donor_b + (1.5 if t >= 12 else 0.0)
        for unit, value in (("T", treated), ("A", donor_a), ("B", donor_b)):
            scm_rows.append({"unit": unit, "date": date, "y": value})
    scm, _ = build_scm_audit(pd.DataFrame(scm_rows), unit_column="unit", date_column="date", outcome_column="y", treated_unit="T", treatment_date=pd.bdate_range("2023-01-02", periods=20)[12])
    assert scm.iloc[0]["evidence_status"] == "scm_design_pass"
    assert scm.iloc[0]["synthetic_did_effect"] > 1.0
    print("[PASS] SCM/SDID reconstructs the pre-path and post-treatment gap")

    x = np.linspace(-1, 1, 400)
    rdd_frame = pd.DataFrame({"running": x, "y": .5 * x + 2.0 * (x >= 0), "balance": x ** 2})
    rdd = build_rdd_audit(rdd_frame, running_column="running", outcome_column="y", cutoff=0, bandwidth=.5, covariate_columns=["balance"])
    assert rdd.iloc[0]["evidence_status"] == "rdd_design_pass"
    assert rdd.iloc[0]["local_treatment_effect"] > 1.9
    print("[PASS] local-linear RDD recovers a cutoff jump and balance checks")

    n = 600
    c1, c2 = rng.normal(size=n), rng.normal(size=n)
    d = .7 * c1 + rng.normal(size=n)
    y = 1.25 * d + .9 * c1 - .4 * c2 + rng.normal(scale=.4, size=n)
    dml_frame = pd.DataFrame({"y": y, "d": d, "c1": c1, "c2": c2, "fold": np.arange(n) % 5})
    dml, _ = build_dml_audit(dml_frame, outcome_column="y", treatment_column="d", control_columns=["c1", "c2"], fold_column="fold")
    assert dml.iloc[0]["evidence_status"] == "dml_effect_evidence"
    assert abs(dml.iloc[0]["orthogonal_effect"] - 1.25) < .15
    print("[PASS] cross-fitted DML recovers a known continuous treatment effect")

    neg = build_negative_control_audit(pd.DataFrame({"date": pd.bdate_range("2023-01-02", periods=n), "factor": d, "outcome": y}), factor_column="factor", outcome_column="outcome", date_column="date", permutation_samples=200)
    assert "negative_control_pass" in neg
    print("[PASS] deterministic permutation and future-to-past controls publish explicit status")


if __name__ == "__main__":
    main()
