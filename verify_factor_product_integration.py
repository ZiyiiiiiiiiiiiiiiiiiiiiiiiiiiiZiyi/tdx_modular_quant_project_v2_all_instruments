"""Static and data-contract checks for integrated factor-curve products."""
from __future__ import annotations

from pathlib import Path

from functions.decision_council.factor_curve_web import FactorStore
from functions.decision_council.holding_factor_products import (
    FACTOR_PRODUCT_DIRNAME,
    FACTOR_WORKBOOK_NAME,
)


PROJECT_DIR = Path(__file__).resolve().parent


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> None:
    runner = (PROJECT_DIR / "functions/decision_council/runner.py").read_text(
        encoding="utf-8"
    )
    monitor = (
        PROJECT_DIR / "functions/decision_council/live_monitor_web.py"
    ).read_text(encoding="utf-8")
    launcher = (PROJECT_DIR / "main_launcher_web.py").read_text(encoding="utf-8")
    _check(
        "build_integrated_products" in runner
        and "holding_factor_products" in runner,
        "SCAP save flow builds factor products automatically",
    )
    _check(
        '"/factors"' in monitor and '"/factor-workbook"' in monitor,
        "live monitor serves curves and workbook",
    )
    _check(
        'parsed.path == "/factors"' in launcher
        and 'parsed.path == "/factor-workbook"' in launcher,
        "result viewer serves curves and workbook",
    )

    run_dir = (
        PROJECT_DIR
        / "results/decision_council/scap/cab_c6dae8d4d69c/e1_l1200/v3"
        / "run20260724_233436"
    )
    product_dir = run_dir / FACTOR_PRODUCT_DIRNAME
    _check(product_dir.is_dir(), "integrated product directory exists")
    store = FactorStore(product_dir)
    meta = store.meta()
    _check(
        len(meta["symbols"]) == 14 and len(meta["factors"]) == 74,
        "factor Web contract exposes all 14 holdings and 74 factors",
    )
    sample = store.series(
        meta["symbols"][0],
        "predicted_return_5d",
        [meta["factors"][0]["name"]],
    )
    _check(
        len(sample["dates"]) > 0 and len(sample["series"]) == 1,
        "factor Web series is readable",
    )
    _check(
        (product_dir / FACTOR_WORKBOOK_NAME).is_file(),
        "integrated Excel workbook exists",
    )


if __name__ == "__main__":
    main()
