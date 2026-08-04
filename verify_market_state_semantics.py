from functions.decision_council.market_state_semantics import build_market_state_authority_disclosure


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


off = build_market_state_authority_disclosure(
    safety_structural_state="weak",
    safety_agent_enabled=True,
    optional_overlay_enabled=False,
    optional_overlay_authorized=False,
    optional_input_valid=False,
    optional_confirmed_label="neutral",
)
check(off["safety_market_state_active"], "safety market state remains explicitly active")
check(off["safety_structural_state"] == "weak", "factual safety state is preserved")
check(not off["optional_regime_overlay_enabled"], "optional overlay is independently disabled")
check(off["optional_regime_overlay_state"] == "unknown", "invalid optional input cannot inherit safety state")
check("no_trade_authority" in off["optional_regime_overlay_authority"], "disabled optional overlay has no trading authority")
check("no_trade_authority" in off["performance_benchmark_authority"], "performance benchmark is attribution only")

on = build_market_state_authority_disclosure(
    safety_structural_state="bull", safety_agent_enabled=True,
    optional_overlay_enabled=True, optional_overlay_authorized=True,
    optional_input_valid=True, optional_confirmed_label="risk_off",
)
check(on["optional_regime_overlay_state"] == "risk_off", "valid optional state is disclosed separately")
check(on["optional_regime_overlay_authority"] == "entry_confirmation_and_exposure_overlay", "authorized overlay authority is explicit")

runner_source = open("functions/decision_council/runner.py", encoding="utf-8").read()
dashboard_source = open("functions/decision_council/live_monitor_dashboard.py", encoding="utf-8").read()
for field in (
    "safety_market_state_active", "safety_structural_state",
    "optional_regime_overlay_enabled", "optional_regime_overlay_state",
    "performance_benchmark_authority", "safety_benchmark_authority",
):
    check(runner_source.count(field) >= 2, f"{field} is persisted and monitored")
check("????????" in dashboard_source, "Web distinguishes optional overlay authority")
check("??????" in dashboard_source, "Web distinguishes safety-state authority")
