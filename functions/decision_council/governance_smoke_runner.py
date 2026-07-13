"""Small smoke checks for governance wiring without a full mainline run."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from functions.decision_council.basket_builder import build_candidate_baskets
from functions.decision_council.basket_state_machine import evaluate_basket_entry
from functions.decision_council.factor_pool_contract import build_role_coverage_report, load_factor_pool_contract


def run_contract_basket_smoke(summary_path: str | Path, *, output_dir: str | Path | None = None) -> dict[str, Path | int | bool]:
    """Validate factor contract and basket construction on a judged factor summary."""
    contract = load_factor_pool_contract(summary_path)
    admitted = contract[contract.get("admitted", pd.Series(False, index=contract.index)).fillna(False).astype(bool)].copy()
    role_report = build_role_coverage_report(contract)
    basket = build_candidate_baskets(
        admitted.rename(
            columns={
                "score": "primary_score",
            }
        )
    )
    entry = evaluate_basket_entry(basket)
    output = Path(output_dir or Path(summary_path).parent / "contract_basket_smoke")
    output.mkdir(parents=True, exist_ok=True)
    contract.to_csv(output / "factor_pool_contract.csv", index=False, encoding="utf-8-sig")
    role_report.to_csv(output / "factor_role_coverage.csv", index=False, encoding="utf-8-sig")
    basket.to_csv(output / "basket_smoke_selection.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([entry]).to_csv(output / "basket_smoke_state.csv", index=False, encoding="utf-8-sig")
    return {
        "output_dir": output,
        "factor_count": int(len(contract)),
        "admitted_count": int(len(admitted)),
        "role_count": int(role_report["role"].nunique()) if not role_report.empty else 0,
        "basket_name_count": int(len(basket)),
        "entry_allowed": bool(entry.get("entry_allowed", False)),
    }
