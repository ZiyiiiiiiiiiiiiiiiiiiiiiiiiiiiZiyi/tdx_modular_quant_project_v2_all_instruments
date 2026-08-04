"""Workbook generation and content status must remain separate."""
from functions.decision_council.holding_factor_products import (
    workbook_content_check_failures,
)


def main() -> int:
    complete = {
        "held_symbol_count": 4,
        "holding_symbol_days": 8,
        "covered_holding_symbol_days": 8,
        "factor_model_count": 74,
    }
    assert workbook_content_check_failures(complete) == []
    missing_day = {**complete, "covered_holding_symbol_days": 7}
    assert workbook_content_check_failures(missing_day) == [
        "holding_symbol_day_factor_coverage"
    ]
    no_factors = {**complete, "factor_model_count": 0}
    assert workbook_content_check_failures(no_factors) == [
        "held_positions_without_factor_models"
    ]
    print("[PASS] generated workbook cannot hide failed content checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
