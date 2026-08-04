"""Static regression checks for dynamic-capacity workbook/report semantics."""
from __future__ import annotations

from pathlib import Path

from functions.decision_council.holding_factor_products import DAILY_COLUMNS


ROOT = Path(__file__).resolve().parent
builder = (ROOT / "tools" / "build_scap_factor_workbook.mjs").read_text(
    encoding="utf-8"
)
product = (
    ROOT / "functions" / "decision_council" / "holding_factor_products.py"
).read_text(encoding="utf-8")

required_daily = {
    "economic_position_cap",
    "search_position_cap",
    "selected_position_count",
    "coverage_mode",
    "coverage_penalty_amount",
    "incremental_expected_wealth_amount",
    "incremental_cvar_amount",
    "model_uncertainty_amount",
    "scenario_risk_penalty_amount",
    "scenario_evidence_state",
    "best_rejected_objective_amount",
}
assert required_daily.issubset(DAILY_COLUMNS)
assert "holding_count.ge(5)" not in product
assert '"full_slot_days"' not in product
assert "capacity_full = valid_capacity & holding_count.ge(economic_cap)" in product
assert "达到当日经济容量的天数" in builder
assert "达到经济容量且仓位缺口>5%的天数" in builder
assert "窗口归一化基准净值（首日=1）" in builder
assert "持有5只" not in builder
assert "COUNTIF('Daily Constraints'" not in builder
assert "dCol.economic_position_cap" in builder
assert builder.count("SUMPRODUCT") >= 4
print("[PASS] dynamic capacity and incremental scenario workbook semantics")
