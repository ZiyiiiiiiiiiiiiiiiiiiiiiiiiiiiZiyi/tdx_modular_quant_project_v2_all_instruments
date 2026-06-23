# -*- coding: utf-8 -*-
"""Run the phase-one daily decision-council backtest."""
from __future__ import annotations

import argparse

from config import (
    CLI_GOVERNANCE_END_DATE,
    CLI_GOVERNANCE_MAX_DAYS,
    CLI_GOVERNANCE_SAFETY_PROXY_MODE,
    CLI_GOVERNANCE_START_DATE,
    CLI_GOVERNANCE_VARIANT,
    GOVERNANCE_OUTPUT_DIR,
    REGISTRY_FRAMEWORK_VERSION,
    assert_valid_configuration,
)
from functions.decision_council.runner import run_governance_backtest
from functions.governance_variant_registry import get_governance_variant_spec
from functions.universe_registry import get_universe_spec


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default=CLI_GOVERNANCE_START_DATE)
    parser.add_argument("--end-date", default=CLI_GOVERNANCE_END_DATE)
    parser.add_argument("--max-days", type=int, default=CLI_GOVERNANCE_MAX_DAYS)
    parser.add_argument("--safety-proxy-mode", choices=["strict", "degraded_backtest"], default=CLI_GOVERNANCE_SAFETY_PROXY_MODE)
    parser.add_argument(
        "--variant",
        choices=["rules_based_president"],
        default=CLI_GOVERNANCE_VARIANT,
    )
    parser.add_argument("--no-live-monitor", action="store_true", help="Disable the low-memory live metrics window.")
    return parser.parse_args()


def main():
    assert_valid_configuration()
    args = parse_args()
    variant_spec = get_governance_variant_spec(args.variant)
    universe_spec = get_universe_spec(variant_spec.universe_name)
    output_dir = GOVERNANCE_OUTPUT_DIR if args.variant == "rules_based_president" else GOVERNANCE_OUTPUT_DIR / args.variant
    saved = run_governance_backtest(
        start_date=args.start_date,
        end_date=args.end_date,
        max_days=args.max_days,
        safety_proxy_mode=args.safety_proxy_mode,
        output_dir=output_dir,
        governance_variant=args.variant,
        enable_sector_cap=variant_spec.enable_sector_cap,
        enable_safety_agent=variant_spec.enable_safety_agent,
        enable_reputation=variant_spec.enable_reputation,
        universe_name=universe_spec.name,
        universe_mode=universe_spec.mode,
        alpha_bundle=variant_spec.alpha_bundle,
        registry_version=REGISTRY_FRAMEWORK_VERSION,
        target_index_codes=tuple(universe_spec.target_index_codes),
        require_constituents=universe_spec.require_constituents,
        allow_fallback=universe_spec.allow_fallback,
        allowed_instrument_types=tuple(universe_spec.allowed_instrument_types),
        enable_quality_filters=universe_spec.quality_filter_enabled,
        show_live_monitor=not args.no_live_monitor,
    )
    print("Decision-council backtest completed.")
    for name, path in sorted(saved.items()):
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
