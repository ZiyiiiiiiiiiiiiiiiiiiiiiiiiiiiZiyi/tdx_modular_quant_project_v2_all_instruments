# -*- coding: utf-8 -*-
"""Governance variant registry."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GovernanceVariantSpec:
    """Declarative definition for one governance variant."""

    variant_name: str
    base_policy: str
    enable_reputation: bool
    enable_sector_cap: bool
    enable_safety_agent: bool
    enable_market_regime_policy: bool
    universe_name: str
    alpha_bundle: str
    position_sizing_mode: str
    description: str
    status: str = "active"
    safety_proxy_mode: str = "strict"
    governance_variant_tag: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant_name": self.variant_name,
            "base_policy": self.base_policy,
            "enable_reputation": self.enable_reputation,
            "enable_sector_cap": self.enable_sector_cap,
            "enable_safety_agent": self.enable_safety_agent,
            "enable_market_regime_policy": self.enable_market_regime_policy,
            "universe_name": self.universe_name,
            "alpha_bundle": self.alpha_bundle,
            "position_sizing_mode": self.position_sizing_mode,
            "description": self.description,
            "status": self.status,
            "safety_proxy_mode": self.safety_proxy_mode,
            "governance_variant_tag": self.governance_variant_tag,
        }


class GovernanceVariantRegistry:
    """Registry of built-in governance variants."""

    def __init__(self):
        self._specs: dict[str, GovernanceVariantSpec] = {}
        self._register_builtins()

    def _register_builtins(self):
        self.register(
            GovernanceVariantSpec(
                variant_name="rules_based_president",
                base_policy="rules_based_president",
                enable_reputation=True,
                enable_sector_cap=False,
                enable_safety_agent=True,
                enable_market_regime_policy=True,
                universe_name="hs300_csi500_a500_strict",
                alpha_bundle="president_core_bundle",
                position_sizing_mode="kelly_managed",
                description="Main governance variant with reputation weighting and safety agent enabled.",
                status="active",
                governance_variant_tag="president",
                extra={
                    "entry_confirmation_mode": "full",
                    "exit_mode": "observe_complex_exit",
                    "selection_weight_mode": "role_balanced",
                    "regime_overlay_mode": "conservative",
                    "risk_hard_gate_enabled": True,
                    "probability_bucket_mode": "breakout_high_confidence",
                },
            )
        )
        self.register(
            GovernanceVariantSpec(
                variant_name="governance_layer_validation",
                base_policy="rules_based_president",
                enable_reputation=False,
                enable_sector_cap=False,
                enable_safety_agent=True,
                enable_market_regime_policy=False,
                universe_name="hs300_csi500_a500_strict",
                alpha_bundle="validation_core_bundle",
                position_sizing_mode="fixed_weight",
                description=(
                    "Diagnostic validation line with a compact equal-weight alpha bundle, "
                    "static market parameters, reputation disabled, and safety kept on. "
                    "Use this to isolate whether the base signal has positive expectancy "
                    "before adding adaptive reputation or regime overlays."
                ),
                status="active",
                governance_variant_tag="layer_validation",
                extra={
                    "purpose": "causal_layer_validation",
                    "recommended_shadow_portfolios": False,
                },
            )
        )
        self.register(
            GovernanceVariantSpec(
                variant_name="governance_core_base",
                base_policy="rules_based_president",
                enable_reputation=False,
                enable_sector_cap=False,
                enable_safety_agent=True,
                enable_market_regime_policy=False,
                universe_name="hs300_csi500_a500_strict",
                alpha_bundle="validation_core_bundle",
                position_sizing_mode="fixed_weight",
                description="Ablation base: compact factors, fixed-percentile entry, simple exits, no regime overlay.",
                status="active",
                governance_variant_tag="core_base",
                extra={
                    "purpose": "layer_ablation_suite",
                    "entry_confirmation_mode": "fixed_percentile_only",
                    "exit_mode": "simple",
                    "layer_added": "none",
                },
            )
        )
        self.register(
            GovernanceVariantSpec(
                variant_name="governance_core_plus_regime",
                base_policy="rules_based_president",
                enable_reputation=False,
                enable_sector_cap=False,
                enable_safety_agent=True,
                enable_market_regime_policy=True,
                universe_name="hs300_csi500_a500_strict",
                alpha_bundle="validation_core_bundle",
                position_sizing_mode="fixed_weight",
                description="Ablation: core base plus market-regime parameter overlay.",
                status="active",
                governance_variant_tag="core_plus_regime",
                extra={
                    "purpose": "layer_ablation_suite",
                    "entry_confirmation_mode": "fixed_percentile_only",
                    "exit_mode": "simple",
                    "layer_added": "market_regime",
                },
            )
        )
        self.register(
            GovernanceVariantSpec(
                variant_name="governance_core_plus_probability",
                base_policy="rules_based_president",
                enable_reputation=False,
                enable_sector_cap=False,
                enable_safety_agent=True,
                enable_market_regime_policy=False,
                universe_name="hs300_csi500_a500_strict",
                alpha_bundle="validation_core_bundle",
                position_sizing_mode="fixed_weight",
                description="Ablation: core base plus probability calibration and expected-edge entry.",
                status="active",
                governance_variant_tag="core_plus_probability",
                extra={
                    "purpose": "layer_ablation_suite",
                    "entry_confirmation_mode": "full",
                    "exit_mode": "simple",
                    "layer_added": "probability_calibration",
                },
            )
        )
        self.register(
            GovernanceVariantSpec(
                variant_name="governance_core_plus_complex_exit",
                base_policy="rules_based_president",
                enable_reputation=False,
                enable_sector_cap=False,
                enable_safety_agent=True,
                enable_market_regime_policy=False,
                universe_name="hs300_csi500_a500_strict",
                alpha_bundle="validation_core_bundle",
                position_sizing_mode="fixed_weight",
                description="Ablation: core probability entry plus complex lifecycle/replacement/trend exits.",
                status="active",
                governance_variant_tag="core_plus_complex_exit",
                extra={
                    "purpose": "layer_ablation_suite",
                    "entry_confirmation_mode": "full",
                    "exit_mode": "active_complex_exit",
                    "layer_added": "complex_exit",
                },
            )
        )
        self.register(
            GovernanceVariantSpec(
                variant_name="governance_full_mainline_control",
                base_policy="rules_based_president",
                enable_reputation=True,
                enable_sector_cap=False,
                enable_safety_agent=True,
                enable_market_regime_policy=True,
                universe_name="hs300_csi500_a500_strict",
                alpha_bundle="president_core_bundle",
                position_sizing_mode="kelly_managed",
                description=(
                    "Full-mainline control for the layer ablation suite. This mirrors "
                    "rules_based_president but writes to a separate output directory so "
                    "diagnostic suites do not overwrite the mainline result folder."
                ),
                status="active",
                governance_variant_tag="full_mainline_control",
                extra={
                    "purpose": "layer_ablation_suite",
                    "entry_confirmation_mode": "full",
                    "exit_mode": "observe_complex_exit",
                    "layer_added": "full_mainline_control",
                },
            )
        )


    def register(self, spec: GovernanceVariantSpec) -> None:
        if spec.variant_name in self._specs:
            raise ValueError(f"Governance variant '{spec.variant_name}' already registered")
        self._specs[spec.variant_name] = spec

    def get(self, name: str) -> GovernanceVariantSpec:
        if name not in self._specs:
            available = sorted(self._specs.keys())
            raise KeyError(f"Unknown governance variant '{name}'. Available: {available}")
        return self._specs[name]

    def list_names(self, *, status: str | None = None) -> list[str]:
        if status is None:
            return sorted(self._specs.keys())
        return sorted(name for name, spec in self._specs.items() if spec.status == status)

    def list_active(self) -> list[str]:
        return self.list_names(status="active")

    def list_experimental(self) -> list[str]:
        return self.list_names(status="experimental")

    def get_output_dir_name(self, variant_name: str) -> str:
        spec = self.get(variant_name)
        tag = spec.governance_variant_tag or variant_name
        return f"governance_{tag}"

    def to_dataframe(self):
        import pandas as pd

        return pd.DataFrame([spec.to_dict() for spec in self._specs.values()])

    def validate(self) -> list[str]:
        errors = []
        valid_policies = {"rules_based_president"}
        valid_position_modes = {"kelly_managed", "equal_weight", "fixed_weight"}
        for name, spec in self._specs.items():
            if not spec.variant_name:
                errors.append("Governance variant spec missing variant_name")
            if spec.base_policy not in valid_policies:
                errors.append(f"Variant '{name}' has invalid base_policy '{spec.base_policy}'")
            if spec.position_sizing_mode not in valid_position_modes:
                errors.append(f"Variant '{name}' has invalid position_sizing_mode '{spec.position_sizing_mode}'")
        return errors


GOVERNANCE_VARIANT_REGISTRY = GovernanceVariantRegistry()


def get_governance_variant_spec(name: str) -> GovernanceVariantSpec:
    return GOVERNANCE_VARIANT_REGISTRY.get(name)


def list_governance_variant_names(*, status: str | None = None) -> list[str]:
    return GOVERNANCE_VARIANT_REGISTRY.list_names(status=status)


def list_active_governance_variants() -> list[str]:
    return GOVERNANCE_VARIANT_REGISTRY.list_active()
