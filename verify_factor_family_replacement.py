"""Product verification for family vacancies and evidence-preserving replacement."""
from __future__ import annotations

import pandas as pd

from functions.factor_selection.factor_candidate_registry import build_factor_candidate_registry
from functions.factor_selection.factor_evidence_grade import grade_factor_evidence
from functions.factor_selection.factor_family_contract import candidate_catalog_frame, family_contract_frame
from functions.factor_selection.factor_replacement_engine import build_replacement_plan


def main() -> None:
    contracts = family_contract_frame()
    required = {"valuation", "profitability", "investment", "cashflow", "growth", "event", "rsi", "orderflow", "breakout", "alternative_proxy", "quality"}
    assert required.issubset(set(contracts["family"]))
    print("[PASS] all requested economic and technical families have explicit contracts")

    catalog = candidate_catalog_frame()
    assert {"fund_earnings_yield_ttm", "fund_book_to_price", "fund_fcf_yield", "fund_roe_ttm_ind_neutral", "fund_asset_growth_neg", "event_buyback_announcement", "rsi_recovery_14", "orderflow_close_drive", "price_volume_breakout"}.issubset(set(catalog["factor_name"]))
    print("[PASS] canonical replacement catalog includes fundamental, event, RSI, orderflow and breakout candidates")

    observed = pd.DataFrame([
        {"factor_name": "fund_book_to_price", "coverage": .95, "best_ic_ir": .30, "positive_ic_ratio": .65, "best_cost_adjusted_top_bottom_spread": .01, "negative_control_pass": True, "causal_grade": "C-C"},
        {"factor_name": "fund_earnings_yield_ttm", "coverage": .95, "best_ic_ir": -.10, "positive_ic_ratio": .40, "best_cost_adjusted_top_bottom_spread": -.01, "negative_control_pass": True, "causal_grade": "C-U"},
    ])
    registry = build_factor_candidate_registry(
        observed,
        available_columns={"cand_fund_book_to_price", "cand_fund_earnings_yield_ttm"},
        pit_level2_state="research_only",
        temporal_isolation_pass=True,
    )
    registry = grade_factor_evidence(registry)
    assert registry.set_index("factor_name").at["fund_book_to_price", "replacement_eligible"]
    assert not registry.set_index("factor_name").at["fund_earnings_yield_ttm", "replacement_eligible"]
    print("[PASS] evidence grading admits a qualified candidate without lowering standards")

    cabinet = pd.DataFrame([
        {"factor_name": "old_value", "raw_column": "old_value", "family": "valuation", "role": "entry_alpha_proxy"},
        {"factor_name": "existing_rsi", "raw_column": "existing_rsi", "family": "rsi", "role": "timing_filter"},
    ])
    result = build_replacement_plan(cabinet, registry, removed_factors={"old_value"})
    rebuilt = result["rebuilt_cabinet"]
    assert "fund_book_to_price" in set(rebuilt["factor_name"])
    assert "fund_earnings_yield_ttm" not in set(rebuilt["factor_name"])
    cashflow = result["family_capacity"].set_index("family").loc["cashflow"]
    assert cashflow["family_status"] in {"VACANT", "BLOCKED_PIT"}
    assert not result["replacement_audit"].empty
    print("[PASS] removed family seat is refilled only by a qualified same-family factor")
    print("[PASS] unqualified families remain visibly vacant instead of forced admission")


if __name__ == "__main__":
    main()
