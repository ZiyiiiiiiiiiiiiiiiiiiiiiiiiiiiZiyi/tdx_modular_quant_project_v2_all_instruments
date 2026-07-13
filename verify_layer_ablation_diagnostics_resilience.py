"""Smoke checks for sparse layer-ablation diagnostics."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from functions.decision_council.layer_ablation_diagnostics import _save_plots


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> int:
    import matplotlib

    matplotlib.use("Agg")
    output = Path("reports/verify_layer_ablation_diagnostics_resilience")
    output.mkdir(parents=True, exist_ok=True)
    summary = pd.DataFrame([
        {"suite_step": "01_core_base"},
        {"suite_step": "10_core_plus_regime"},
    ])
    increments = pd.DataFrame([
        {"suite_step": "01_core_base"},
        {"suite_step": "10_core_plus_regime"},
    ])
    payoff_without_10d = pd.DataFrame([
        {"suite_step": "01_core_base", "horizon_days": 5, "side": "buy", "expectancy": 0.0}
    ])
    saved = _save_plots(
        summary,
        payoff_without_10d,
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        increments,
        output,
        "sparse",
    )
    check("overview_plot" in saved and saved["overview_plot"].exists(), "overview tolerates missing metric columns")
    check("incremental_plot" in saved and saved["incremental_plot"].exists(), "incremental plot tolerates missing delta columns")
    check("payoff_plot" not in saved, "filtered-empty plot is not falsely registered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
