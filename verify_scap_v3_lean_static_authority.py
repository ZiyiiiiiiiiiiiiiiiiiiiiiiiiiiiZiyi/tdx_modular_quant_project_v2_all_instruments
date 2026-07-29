"""Static authority graph checks that do not execute the strategy."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def passed(message: str) -> None:
    print(f"[PASS] {message}")


lean_path = ROOT / "functions" / "decision_council" / "scap_v3_lean.py"
policy_path = ROOT / "functions" / "decision_council" / "policy.py"
retail_path = ROOT / "functions" / "decision_council" / "retail_execution.py"
pending_path = ROOT / "functions" / "decision_council" / "pending_orders.py"
execution_path = ROOT / "functions" / "decision_council" / "execution_runtime.py"

lean_source = lean_path.read_text(encoding="utf-8")
lean_tree = ast.parse(lean_source)
optimizer_calls = [
    node
    for node in ast.walk(lean_tree)
    if isinstance(node, ast.Call)
    and isinstance(node.func, ast.Name)
    and node.func.id == "optimize_action_proposals"
]
assert len(optimizer_calls) == 1
passed("Lean authority module contains exactly one optimizer call site")

policy_source = policy_path.read_text(encoding="utf-8")
lean_branch = policy_source.index('if str(context.control_mode).strip().lower() == "aggressive_lean"')
legacy_selector = policy_source.index("_select_scap_discrete_entries(", lean_branch)
assert lean_branch < legacy_selector
passed("Lean returns before the legacy selector and continuous allocator")

retail_source = retail_path.read_text(encoding="utf-8")
tree = ast.parse(retail_source)
adapter = next(
    node
    for node in tree.body
    if isinstance(node, ast.FunctionDef) and node.name == "adapt_retail_buy_order"
)
adapter_source = ast.get_source_segment(retail_source, adapter) or ""
plan_branch = adapter_source.split("if action_plan_authorized:", 1)[1].split(
    "if initial_shares >= minimum_buy_quantity:", 1
)[0]
for forbidden in (
    "entry_confirmed",
    "primary_score",
    "scap_candidate_utility",
    "add_allowed",
):
    assert forbidden not in plan_branch
passed("ActionPlan execution branch contains no post-plan soft-score veto")

pending_source = pending_path.read_text(encoding="utf-8")
for required in (
    '"action_plan_id"',
    '"action_proposal_id"',
    '"action_plan_selected"',
    '"scap_v31_authority_tier"',
    '"scap_v31_authority_contract"',
    '"cash_reservation_id"',
):
    assert required in pending_source
passed("pending schema preserves plan, proposal and cash-reservation lineage")

execution_source = execution_path.read_text(encoding="utf-8")
register_start = execution_source.index("def register_orders(")
register_source = execution_source[register_start:]
for required in (
    '"action_plan_id": order.get("action_plan_id", "")',
    '"action_proposal_id": order.get("action_proposal_id", "")',
    '"action_plan_selected": order.get("action_plan_selected", False)',
    '"action_plan_contract": order.get("action_plan_contract", "")',
    '"scap_v31_authority_tier": order.get(',
    '"scap_v31_authority_contract": order.get(',
    '"_cash_reservation_id", order.get("cash_reservation_id", "")',
):
    assert required in register_source
passed("order registration copies ActionPlan and cash-reservation lineage into pending state")

for required in (
    "strategic_exposure_budget",
    "signal_supported_exposure",
    "integer_feasible_exposure",
    "planned_exposure",
):
    assert required in lean_source
passed("Lean authority emits the four pre-fill exposure layers")
