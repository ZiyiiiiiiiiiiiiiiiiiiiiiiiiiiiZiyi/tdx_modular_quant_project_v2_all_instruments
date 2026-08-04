from pathlib import Path


source = Path("tools/run_controlled_state_family_ablations.py").read_text(
    encoding="utf-8"
)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


check('initial_cash=20_000.0' in source, "ablation cash remains fixed")
check('min_cash_buffer=1_000.0' in source, "ablation cash buffer remains fixed")
check(
    '"scap_candidate_pool_per_thesis"] = 1' in source,
    "family experiment changes only the declared reserve setting",
)
check(
    'overlay_enabled=True' in source and 'overlay_mode="full"' in source,
    "state experiment explicitly enables the full optional overlay",
)
check(
    'overlay_enabled=False' in source and 'overlay_mode="off"' in source,
    "family experiment keeps the optional overlay off",
)
check(
    'factor_cabinet_run_id="pruned_run20260714_184846_581132_20260715_230524"'
    in source,
    "factor cabinet remains frozen across ablations",
)
check('"decision_authority": "none_research_only"' in source, "outputs deny trading authority")
