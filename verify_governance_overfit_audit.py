"""Truth and fail-closed tests for DSR, PBO, and SPA-style audits."""
from __future__ import annotations

import numpy as np
import pandas as pd

from functions.decision_council.overfit_audit import build_overfit_audit_reports


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def fixture(periods=320):
    rng = np.random.default_rng(20260717)
    common = rng.normal(0.0, 0.006, periods)
    return pd.DataFrame({
        "date": pd.bdate_range("2021-01-04", periods=periods),
        "baseline": common + rng.normal(0.0, 0.006, periods),
        "noise_a": common + rng.normal(0.0, 0.006, periods),
        "noise_b": common + rng.normal(0.0, 0.006, periods),
        "strong": common + 0.0025 + rng.normal(0.0, 0.004, periods),
        "weak": common + 0.0002 + rng.normal(0.0, 0.006, periods),
    })


def main():
    source = fixture()
    before = source.copy(deep=True)
    reports = build_overfit_audit_reports(
        source,
        baseline_strategy="baseline",
        bootstrap_samples=500,
        minimum_observations=60,
    )
    dsr = reports["governance_overfit_deflated_sharpe"].set_index("strategy")
    spa = reports["governance_overfit_spa"].set_index("strategy")
    pbo = reports["governance_overfit_pbo"].iloc[0]
    check(0.0 <= float(pbo["pbo"]) <= 1.0 and int(pbo["cscv_combinations"]) > 0, "CSCV/PBO is estimated and bounded")
    check(dsr.at["strong", "deflated_sharpe_probability"] > dsr.at["weak", "deflated_sharpe_probability"], "DSR ranks planted strong evidence above weak evidence")
    check(dsr.at["strong", "evidence_status"] == "deflated_sharpe_evidence", "strong strategy survives selection-bias Sharpe deflation")
    check(spa.at["strong", "evidence_status"] == "superior_predictive_evidence", "strong strategy survives familywise block-bootstrap comparison")
    check(spa.at["noise_a", "evidence_status"] == "superiority_not_established", "noise alternative is not promoted")
    check(source.equals(before), "overfit audit does not mutate strategy returns")
    repeated = build_overfit_audit_reports(source, baseline_strategy="baseline", bootstrap_samples=500)
    check(np.allclose(spa["familywise_bootstrap_p_value"], repeated["governance_overfit_spa"].set_index("strategy")["familywise_bootstrap_p_value"]), "SPA-style bootstrap is reproducible")
    short = build_overfit_audit_reports(
        fixture(periods=20), baseline_strategy="baseline", bootstrap_samples=50, minimum_observations=60,
    )
    check(short["governance_overfit_deflated_sharpe"]["evidence_status"].eq("insufficient_observations").all(), "short DSR evidence fails closed")
    check(short["governance_overfit_pbo"].iloc[0]["evidence_status"] == "insufficient_observations", "short PBO evidence fails closed")
    check(short["governance_overfit_spa"]["evidence_status"].eq("insufficient_observations").all(), "short SPA evidence fails closed")
    try:
        build_overfit_audit_reports(source[["date", "strong"]], baseline_strategy="strong")
    except ValueError:
        print("[PASS] single-strategy misuse fails loudly")
    else:
        raise AssertionError("single-strategy misuse fails loudly")
    print("[PASS] overfit audit product verification completed")


if __name__ == "__main__":
    main()
