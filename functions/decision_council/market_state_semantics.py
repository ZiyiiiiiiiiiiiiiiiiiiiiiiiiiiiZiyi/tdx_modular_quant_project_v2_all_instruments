"""Explicit authority labels for market state and benchmark consumers."""
from __future__ import annotations


def build_market_state_authority_disclosure(
    *,
    safety_structural_state: str,
    safety_agent_enabled: bool,
    optional_overlay_enabled: bool,
    optional_overlay_authorized: bool,
    optional_input_valid: bool,
    optional_confirmed_label: str,
) -> dict:
    optional_state = (
        str(optional_confirmed_label or "unknown")
        if bool(optional_input_valid)
        else "unknown"
    )
    return {
        "market_state_semantics_contract_version": "v1_explicit_authority",
        "safety_market_state_active": bool(safety_agent_enabled),
        "safety_structural_state": str(safety_structural_state or "unknown"),
        "safety_market_state_authority": (
            "hard_safety_cap_and_scap_policy_band"
            if bool(safety_agent_enabled)
            else "disabled"
        ),
        "optional_regime_overlay_enabled": bool(optional_overlay_enabled),
        "optional_regime_overlay_authorized": bool(optional_overlay_authorized),
        "optional_regime_overlay_state": optional_state,
        "optional_regime_overlay_authority": (
            "entry_confirmation_and_exposure_overlay"
            if bool(optional_overlay_authorized)
            else "diagnostics_only_no_trade_authority"
        ),
        "performance_benchmark_authority": "attribution_only_no_trade_authority",
        "safety_benchmark_authority": "safety_market_state_input",
    }
