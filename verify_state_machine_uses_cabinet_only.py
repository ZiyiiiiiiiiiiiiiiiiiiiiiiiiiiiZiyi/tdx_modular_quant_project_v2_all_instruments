"""Verify state-machine cabinet loader and guard against admitted_all coupling."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from functions.decision_council.factor_cabinet_loader import build_state_inputs_from_cabinet, load_factor_cabinet


def main() -> int:
    roots = sorted(Path("results/factor_cabinet").glob("run*/factor_cabinet.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not roots:
        print("[SKIP] no factor cabinet json found")
        return 0
    cabinet = load_factor_cabinet(roots[0])
    sample_factors = cabinet["factor_name"].head(5).tolist()
    scores = pd.DataFrame({"date": [pd.Timestamp("2024-01-01")], "symbol": ["sh600000"], **{factor: [0.5] for factor in sample_factors}})
    state = build_state_inputs_from_cabinet(scores, cabinet)
    if state.empty or "entry_alpha_score" not in state.columns or "entry_source" not in state.columns:
        print("[FAIL] cabinet state inputs missing required fields")
        return 1
    text = ""
    for path in [Path("functions/decision_council/factor_cabinet_loader.py")]:
        text += path.read_text(encoding="utf-8")
    if "admitted_all" in text:
        print("[FAIL] cabinet loader references admitted_all")
        return 1
    print(f"[PASS] state inputs built from cabinet only: {roots[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
