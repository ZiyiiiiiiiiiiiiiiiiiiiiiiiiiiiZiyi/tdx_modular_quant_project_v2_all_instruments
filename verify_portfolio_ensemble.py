# -*- coding: utf-8 -*-
import pandas as pd

from functions.portfolio_optimizer import apply_sector_cap, equal_weight_portfolio, inverse_vol_portfolio
from functions.strategy_ensemble import build_equal_strategy_ensemble


def verify_portfolio_ensemble():
    failures: list[str] = []
    print("=== Verify portfolio optimizer and ensemble ===")

    selection = pd.DataFrame(
        {
            "date": ["2024-01-31"] * 4,
            "symbol": ["a", "b", "c", "d"],
            "sector_parent": ["bank", "bank", "tech", "tech"],
            "volatility_20": [0.1, 0.2, 0.3, 0.4],
        }
    )
    equal_weight = equal_weight_portfolio(selection)
    inverse_vol = inverse_vol_portfolio(selection)
    capped = apply_sector_cap(inverse_vol, cap=0.55)

    for label, frame in {"equal": equal_weight, "inverse_vol": inverse_vol, "capped": capped}.items():
        if "target_weight" not in frame.columns:
            failures.append(f"{label} portfolio missing target_weight")
            print(f"[FAIL] {label} portfolio missing target_weight")
        else:
            print(f"[PASS] {label} portfolio target_weight generated")

    score_frames = {
        "alpha": pd.DataFrame({"date": ["2024-01-31"], "symbol": ["a"], "score": [1.0]}),
        "beta": pd.DataFrame({"date": ["2024-01-31"], "symbol": ["a"], "score": [0.5]}),
    }
    ensemble = build_equal_strategy_ensemble(score_frames)
    if ensemble.empty or "ensemble_score" not in ensemble.columns:
        failures.append("ensemble output missing ensemble_score")
        print("[FAIL] ensemble output missing ensemble_score")
    else:
        print("[PASS] ensemble output generated")

    print()
    if failures:
        print("Portfolio and ensemble verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Portfolio and ensemble verification passed.")


if __name__ == "__main__":
    verify_portfolio_ensemble()
